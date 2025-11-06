import os
import re
import gzip
import json
import time
import uuid
import zlib
import base64
import string
import asyncio
import hashlib
import secrets
import datetime
import datetime as dt
import dataclasses
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from enum import Enum
from functools import lru_cache, wraps
from operator import itemgetter
from typing import TYPE_CHECKING, Any, Optional, Union, cast
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.db import ProgrammingError
from django.db.utils import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import get_template
from django.urls import URLPattern, re_path
from django.utils import timezone
from django.utils.cache import patch_cache_control

import pytz
import orjson
import lzstring
import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from celery.result import AsyncResult
from celery.schedules import crontab
from dateutil import parser
from dateutil.relativedelta import relativedelta
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.utils.encoders import JSONEncoder
from user_agents import parse

from posthog.cloud_utils import get_cached_instance_license, is_cloud
from posthog.constants import AvailableFeature
from posthog.exceptions import RequestParsingError, UnspecifiedCompressionFallbackParsingError
from posthog.exceptions_capture import capture_exception
from posthog.git import get_git_branch, get_git_commit_short
from posthog.metrics import KLUDGES_COUNTER
from posthog.redis import get_client

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

    from posthog.models import Dashboard, DashboardTile, InsightVariable, Team, User

DATERANGE_MAP = {
    "second": datetime.timedelta(seconds=1),
    "minute": datetime.timedelta(minutes=1),
    "hour": datetime.timedelta(hours=1),
    "day": datetime.timedelta(days=1),
    "week": datetime.timedelta(weeks=1),
    "month": datetime.timedelta(days=31),
}
ANONYMOUS_REGEX = r"^([a-z0-9]+\-){4}([a-z0-9]+)$"
UUID_REGEX = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

DEFAULT_DATE_FROM_DAYS = 7

logger = structlog.get_logger(__name__)

# https://stackoverflow.com/questions/4060221/how-to-reliably-open-a-file-in-the-same-directory-as-a-python-script
__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


class PotentialSecurityProblemException(Exception):
    """
    When providing an absolutely-formatted URL
    we will not provide one that has an unexpected hostname
    because an attacker might use that to redirect traffic somewhere *bad*
    """

    pass


def absolute_uri(url: Optional[str] = None) -> str:
    """
    Returns an absolutely-formatted URL based on the `SITE_URL` config.

    If the provided URL is already absolutely formatted
    it does not allow anything except the hostname of the SITE_URL config
    """
    if not url:
        return settings.SITE_URL

    provided_url = urlparse(url)
    if provided_url.hostname and provided_url.scheme:
        site_url = urlparse(settings.SITE_URL)
        provided_url = provided_url
        if (
            site_url.hostname != provided_url.hostname
            or site_url.port != provided_url.port
            or site_url.scheme != provided_url.scheme
        ):
            raise PotentialSecurityProblemException(f"It is forbidden to provide an absolute URI using {url}")

    return urljoin(settings.SITE_URL.rstrip("/") + "/", url.lstrip("/"))


def get_previous_day(at: Optional[datetime.datetime] = None) -> tuple[datetime.datetime, datetime.datetime]:
    """
    Returns a pair of datetimes, representing the start and end of the preceding day.
    `at` is the datetime to use as a reference point.
    """

    if not at:
        at = timezone.now()

    period_end: datetime.datetime = datetime.datetime.combine(
        at - datetime.timedelta(days=1),
        datetime.time.max,
        tzinfo=ZoneInfo("UTC"),
    )  # end of the previous day

    period_start: datetime.datetime = datetime.datetime.combine(
        period_end,
        datetime.time.min,
        tzinfo=ZoneInfo("UTC"),
    )  # start of the previous day

    return (period_start, period_end)


def get_current_day(at: Optional[datetime.datetime] = None) -> tuple[datetime.datetime, datetime.datetime]:
    """
    Returns a pair of datetimes, representing the start and end of the current day.
    `at` is the datetime to use as a reference point.
    """

    if not at:
        at = timezone.now()

    period_end: datetime.datetime = datetime.datetime.combine(
        at,
        datetime.time.max,
        tzinfo=ZoneInfo("UTC"),
    )  # end of the reference day

    period_start: datetime.datetime = datetime.datetime.combine(
        period_end,
        datetime.time.min,
        tzinfo=ZoneInfo("UTC"),
    )  # start of the reference day

    return (period_start, period_end)


def relative_date_parse_with_delta_mapping(
    input: str,
    timezone_info: ZoneInfo,
    *,
    always_truncate: bool = False,
    human_friendly_comparison_periods: bool = False,
    now: Optional[datetime.datetime] = None,
    increase: bool = False,
) -> tuple[datetime.datetime, Optional[dict[str, int]], str | None]:
    """
    Returns the parsed datetime, along with the period mapping - if the input was a relative datetime string.

    :increase controls whether to add relative delta to the current time or subtract
        Should later control this using +/- infront of the input regex
    """
    try:
        try:
            # This supports a few formats, but we primarily care about:
            # YYYY-MM-DD, YYYY-MM-DD[T]hh:mm, YYYY-MM-DD[T]hh:mm:ss, YYYY-MM-DD[T]hh:mm:ss.ssssss
            # (if a timezone offset is specified, we use it, otherwise we assume project timezone)
            parsed_dt = parser.isoparse(input)
        except ValueError:
            # Fallback to also parse dates without zero-padding, e.g. 2021-1-1 - parser.isoparse doesn't support this
            parsed_dt = datetime.datetime.strptime(input, "%Y-%m-%d")
    except ValueError:
        pass
    else:
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone_info)
        else:
            parsed_dt = parsed_dt.astimezone(timezone_info)
        return parsed_dt, None, None

    regex = r"\-?(?P<number>[0-9]+)?(?P<kind>[hdwmqysHDWMQY])(?P<position>Start|End)?"
    match = re.search(regex, input)
    parsed_dt = (now or dt.datetime.now()).astimezone(timezone_info)
    delta_mapping: dict[str, int] = {}
    if not match:
        return parsed_dt, delta_mapping, None

    delta_mapping = get_delta_mapping_for(
        **match.groupdict(),
        human_friendly_comparison_periods=human_friendly_comparison_periods,
    )

    if increase:
        parsed_dt += relativedelta(**delta_mapping)  # type: ignore
    else:
        parsed_dt -= relativedelta(**delta_mapping)  # type: ignore

    if always_truncate:
        # Truncate to the start of the hour for hour-precision datetimes, to the start of the day for larger intervals
        # TODO: Remove this from this function, this should not be the responsibility of it
        if "hours" in delta_mapping:
            parsed_dt = parsed_dt.replace(minute=0, second=0, microsecond=0)
        else:
            parsed_dt = parsed_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return parsed_dt, delta_mapping, match.group("position") or None


def get_delta_mapping_for(
    *,
    kind: str,
    number: Optional[str] = None,
    position: Optional[str] = None,
    human_friendly_comparison_periods: bool = False,
) -> dict[str, int]:
    delta_mapping: dict[str, int] = {}

    if kind == "h":
        if number:
            delta_mapping["hours"] = int(number)
        if position == "Start":
            delta_mapping["minute"] = 0
            delta_mapping["second"] = 0
            delta_mapping["microsecond"] = 0
        elif position == "End":
            delta_mapping["minute"] = 59
            delta_mapping["second"] = 59
            delta_mapping["microsecond"] = 999999
    elif kind == "d":
        if number:
            delta_mapping["days"] = int(number)
        if position == "Start":
            delta_mapping["hour"] = 0
            delta_mapping["minute"] = 0
            delta_mapping["second"] = 0
            delta_mapping["microsecond"] = 0
        elif position == "End":
            delta_mapping["hour"] = 23
            delta_mapping["minute"] = 59
            delta_mapping["second"] = 59
            delta_mapping["microsecond"] = 999999
    elif kind == "w":
        if number:
            delta_mapping["weeks"] = int(number)
    elif kind == "m":
        if number:
            if human_friendly_comparison_periods:
                delta_mapping["weeks"] = 4
            else:
                delta_mapping["months"] = int(number)
        if position == "Start":
            delta_mapping["day"] = 1
        elif position == "End":
            delta_mapping["day"] = 31
    elif kind == "M":
        if number:
            delta_mapping["minutes"] = int(number)
    elif kind == "s":
        if number:
            delta_mapping["seconds"] = int(number)
    elif kind == "q":
        if number:
            delta_mapping["weeks"] = 13 * int(number)
    elif kind == "y":
        if number:
            if human_friendly_comparison_periods:
                delta_mapping["weeks"] = 52
            else:
                delta_mapping["years"] = int(number)
        if position == "Start":
            delta_mapping["month"] = 1
            delta_mapping["day"] = 1
        elif position == "End":
            delta_mapping["day"] = 31

    return delta_mapping


def relative_date_parse(
    input: str,
    timezone_info: ZoneInfo,
    *,
    always_truncate: bool = False,
    human_friendly_comparison_periods: bool = False,
    now: Optional[datetime.datetime] = None,
    increase: bool = False,
) -> datetime.datetime:
    return relative_date_parse_with_delta_mapping(
        input,
        timezone_info,
        always_truncate=always_truncate,
        human_friendly_comparison_periods=human_friendly_comparison_periods,
        now=now,
        increase=increase,
    )[0]


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    if plural is None:
        plural = singular + "s"
    return f"{count} {singular if count == 1 else plural}"


def human_list(items: Sequence[str]) -> str:
    """Join iterable of strings into a human-readable list ("a, b, and c").
    Uses the Oxford comma only when there are at least 3 items."""
    if len(items) < 3:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def get_js_url(request: HttpRequest) -> str:
    """
    As the web app may be loaded from a non-localhost url (e.g. from the worker container calling the web container)
    it is necessary to set the JS_URL host based on the calling origin.
    """
    if settings.DEBUG and settings.JS_URL == "http://localhost:8234":
        return f"http://{request.get_host().split(':')[0]}:8234"
    return settings.JS_URL


def get_context_for_template(
    template_name: str,
    request: HttpRequest,
    context: Optional[dict] = None,
    team_for_public_context: Optional["Team"] = None,
) -> dict:
    if context is None:
        context = {}

    context["opt_out_capture"] = settings.OPT_OUT_CAPTURE
    context["self_capture"] = settings.SELF_CAPTURE
    context["region"] = get_instance_region()

    if settings.STRIPE_PUBLIC_KEY:
        context["stripe_public_key"] = settings.STRIPE_PUBLIC_KEY

    context["git_rev"] = get_git_commit_short()  # Include commit in prod for the `console.info()` message
    if settings.DEBUG and not settings.TEST:
        context["debug"] = True
        context["git_branch"] = get_git_branch()
        source_path = "src/index.tsx"
        if template_name == "exporter.html":
            source_path = "src/exporter/index.tsx"
        elif template_name == "render_query.html":
            source_path = "src/render-query/index.tsx"
        # Add vite dev scripts for development
        context["vite_dev_scripts"] = f"""
        <script nonce="{request.csp_nonce}" type="module">
            import RefreshRuntime from 'http://localhost:8234/@react-refresh'
            RefreshRuntime.injectIntoGlobalHook(window)
            window.$RefreshReg$ = () => {{}}
            window.$RefreshSig$ = () => (type) => type
            window.__vite_plugin_react_preamble_installed__ = true
        </script>
        <!-- Vite development server -->
        <script type="module" src="http://localhost:8234/@vite/client"></script>
        <script type="module" src="http://localhost:8234/{source_path}"></script>"""

    context["js_posthog_ui_host"] = ""

    if settings.E2E_TESTING:
        context["e2e_testing"] = True
        context["js_posthog_api_key"] = "phc_ex7Mnvi4DqeB6xSQoXU1UVPzAmUIpiciRKQQXGGTYQO"
        context["js_posthog_host"] = "https://internal-j.posthog.com"
        context["js_posthog_ui_host"] = "https://us.posthog.com"

    elif settings.SELF_CAPTURE:
        if posthoganalytics.api_key:
            context["js_posthog_api_key"] = posthoganalytics.api_key
            context["js_posthog_host"] = ""  # Becomes location.origin in the frontend
    else:
        context["js_posthog_api_key"] = "sTMFPsFhdP1Ssg"
        context["js_posthog_host"] = "https://internal-j.posthog.com"
        context["js_posthog_ui_host"] = "https://us.posthog.com"

    context["js_capture_time_to_see_data"] = settings.CAPTURE_TIME_TO_SEE_DATA
    context["js_kea_verbose_logging"] = settings.KEA_VERBOSE_LOGGING
    context["js_app_state_logging_sample_rate"] = settings.APP_STATE_LOGGING_SAMPLE_RATE
    context["js_url"] = get_js_url(request)

    posthog_app_context: dict[str, Any] = {
        "persisted_feature_flags": settings.PERSISTED_FEATURE_FLAGS,
        "anonymous": not request.user or not request.user.is_authenticated,
    }

    posthog_bootstrap: dict[str, Any] = {}
    posthog_distinct_id: Optional[str] = None

    # Set the frontend app context
    if not request.GET.get("no-preloaded-app-context"):
        from posthog.api.project import ProjectSerializer
        from posthog.api.shared import TeamPublicSerializer
        from posthog.api.team import TeamSerializer
        from posthog.api.user import UserSerializer
        from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES, UserAccessControl
        from posthog.user_permissions import UserPermissions
        from posthog.views import preflight_check

        posthog_app_context = {
            "current_user": None,
            "current_project": None,
            "current_team": None,
            "preflight": json.loads(preflight_check(request).getvalue()),
            "default_event_name": "$pageview",
            "switched_team": getattr(request, "switched_team", None),
            "suggested_users_with_access": getattr(request, "suggested_users_with_access", None),
            "commit_sha": context["git_rev"],
            "livestream_host": settings.LIVESTREAM_HOST,
            **posthog_app_context,
        }

        if team_for_public_context:
            # This allows for refreshing shared insights and dashboards
            posthog_app_context["current_team"] = TeamPublicSerializer(
                team_for_public_context, context={"request": request}, many=False
            ).data
        elif request.user.pk:
            user = cast("User", request.user)
            user_permissions = UserPermissions(user=user, team=user.team)
            user_access_control = UserAccessControl(user=user, team=user.team)
            posthog_app_context["effective_resource_access_control"] = {
                resource: user_access_control.effective_access_level_for_resource(resource)
                for resource in ACCESS_CONTROL_RESOURCES
            }
            posthog_app_context["resource_access_control"] = {
                resource: user_access_control.access_level_for_resource(resource)
                for resource in ACCESS_CONTROL_RESOURCES
            }
            user_serialized = UserSerializer(
                request.user,
                context={
                    "request": request,
                    "user_permissions": user_permissions,
                    "user_access_control": user_access_control,
                },
                many=False,
            )
            posthog_app_context["current_user"] = user_serialized.data
            posthog_distinct_id = user_serialized.data.get("distinct_id")
            if user.team:
                team_serialized = TeamSerializer(
                    user.team,
                    context={
                        "request": request,
                        "user_permissions": user_permissions,
                        "user_access_control": user_access_control,
                    },
                    many=False,
                )
                posthog_app_context["current_team"] = team_serialized.data
                project_serialized = ProjectSerializer(
                    user.team.project,
                    context={"request": request, "user_permissions": user_permissions},
                    many=False,
                )
                posthog_app_context["current_project"] = project_serialized.data
                posthog_app_context["frontend_apps"] = get_frontend_apps(user.team.pk)
                posthog_app_context["default_event_name"] = get_default_event_name(user.team)

    # JSON dumps here since there may be objects like Queries
    # that are not serializable by Django's JSON serializer
    context["posthog_app_context"] = json.dumps(posthog_app_context, default=json_uuid_convert)

    if posthog_distinct_id:
        groups = {}
        group_properties = {}
        person_properties = {}
        if request.user and request.user.is_authenticated:
            user = cast("User", request.user)
            person_properties["email"] = user.email
            person_properties["joined_at"] = user.date_joined.isoformat()
            if user.organization:
                groups["organization"] = str(user.organization.id)
                group_properties["organization"] = {
                    "name": user.organization.name,
                    "created_at": user.organization.created_at.isoformat(),
                }

        feature_flags = posthoganalytics.get_all_flags(
            posthog_distinct_id,
            only_evaluate_locally=True,
            person_properties=person_properties,
            groups=groups,
            group_properties=group_properties,
        )
        # don't forcefully set distinctID, as this breaks the link for anonymous users coming from `posthog.com`.
        posthog_bootstrap["featureFlags"] = feature_flags

    # This allows immediate flag availability on the frontend, atleast for flags
    # that don't depend on any person properties. To get these flags, add person properties to the
    # `get_all_flags` call above.
    context["posthog_bootstrap"] = json.dumps(posthog_bootstrap)

    context["posthog_js_uuid_version"] = settings.POSTHOG_JS_UUID_VERSION

    return context


def render_template(
    template_name: str,
    request: HttpRequest,
    context: Optional[dict] = None,
    *,
    team_for_public_context: Optional["Team"] = None,
    status_code: Optional[int] = None,
) -> HttpResponse:
    """Render Django template.

    If team_for_public_context is provided, this means this is a public page such as a shared dashboard.
    """

    context = get_context_for_template(template_name, request, context, team_for_public_context)
    template = get_template(template_name)

    html = template.render(context, request=request)
    response = HttpResponse(html)
    if status_code:
        response.status_code = status_code
    if not request.user.is_anonymous:
        patch_cache_control(response, no_store=True)

    return response


async def initialize_self_capture_api_token():
    """
    Configures `posthoganalytics` for self-capture, in an ASGI-compatible, async way.
    """

    User = apps.get_model("posthog", "User")
    Team = apps.get_model("posthog", "Team")
    try:
        user = (
            await User.objects.filter(last_login__isnull=False)
            .order_by("-last_login")
            .select_related("current_team")
            .afirst()
        )
        # Get the current user's team (or first team in the instance) to set self capture configs
        team = None
        if user and getattr(user, "current_team", None):
            team = user.current_team
        else:
            team = await Team.objects.only("api_token").afirst()
        local_api_key = team.api_token if team else None
    except (User.DoesNotExist, Team.DoesNotExist, ProgrammingError):
        local_api_key = None

    # This is running _after_ PostHogConfig.ready(), so we re-enable posthoganalytics while setting the params
    if local_api_key is not None:
        posthoganalytics.disabled = False
        posthoganalytics.api_key = local_api_key
        posthoganalytics.host = settings.SITE_URL


def get_default_event_name(team: "Team"):
    from posthog.models import EventDefinition

    if EventDefinition.objects.filter(team=team, name="$pageview").exists():
        return "$pageview"
    elif EventDefinition.objects.filter(team=team, name="$screen").exists():
        return "$screen"
    return "$pageview"


def get_frontend_apps(team_id: int) -> dict[int, dict[str, Any]]:
    from posthog.models import Plugin, PluginSourceFile

    plugin_configs = (
        Plugin.objects.filter(pluginconfig__team_id=team_id, pluginconfig__enabled=True)
        .filter(
            pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED,
            pluginsourcefile__filename="frontend.tsx",
        )
        .values(
            "pluginconfig__id",
            "pluginconfig__config",
            "config_schema",
            "id",
            "plugin_type",
            "name",
        )
        .all()
    )

    frontend_apps = {}
    for p in plugin_configs:
        config = p["pluginconfig__config"] or {}
        config_schema = p["config_schema"] or {}
        secret_fields = {field["key"] for field in config_schema if field.get("secret")}
        for key in secret_fields:
            if key in config:
                config[key] = "** SECRET FIELD **"
        frontend_apps[p["pluginconfig__id"]] = {
            "pluginConfigId": p["pluginconfig__id"],
            "pluginId": p["id"],
            "pluginType": p["plugin_type"],
            "name": p["name"],
            "url": f"/app/{p['pluginconfig__id']}/",
            "config": config,
        }

    return frontend_apps


def json_uuid_convert(o):
    if isinstance(o, uuid.UUID):
        return str(o)


def friendly_time(seconds: float):
    minutes, seconds = divmod(seconds, 60.0)
    hours, minutes = divmod(minutes, 60.0)
    return "{hours}{minutes}{seconds}".format(
        hours=f"{int(hours)} hours " if hours > 0 else "",
        minutes=f"{int(minutes)} minutes " if minutes > 0 else "",
        seconds=f"{int(seconds)} seconds" if seconds > 0 or (minutes == 0 and hours == 0) else "",
    ).strip()


def get_ip_address(request: HttpRequest) -> str:
    """use requestobject to fetch client machine's IP Address"""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")  # Real IP address of client Machine

    # Strip port from ip address as Azure gateway handles x-forwarded-for incorrectly
    if ip and len(ip.split(":")) == 2:
        ip = ip.split(":")[0]

    return ip


def get_short_user_agent(request: HttpRequest) -> str:
    """Returns browser and OS info from user agent, eg: 'Chrome 135.0.0 on macOS 10.15'"""
    user_agent_str = request.META.get("HTTP_USER_AGENT")
    if not user_agent_str:
        return ""

    user_agent = parse(user_agent_str)

    # strip the last (patch/build) number from the version, it can change frequently
    browser_version = ".".join(str(x) for x in user_agent.browser.version[:3])
    os_version = ".".join(str(x) for x in user_agent.os.version[:2])

    return f"{user_agent.browser.family} {browser_version} on {user_agent.os.family} {os_version}"


def dict_from_cursor_fetchall(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def convert_property_value(input: Union[str, bool, dict, list, int, Optional[str]]) -> str:
    if isinstance(input, bool):
        if input is True:
            return "true"
        return "false"
    if isinstance(input, dict) or isinstance(input, list):
        return json.dumps(input, sort_keys=True)
    return str(input)


def get_compare_period_dates(
    date_from: datetime.datetime,
    date_to: datetime.datetime,
    date_from_delta_mapping: Optional[dict[str, int]],
    date_to_delta_mapping: Optional[dict[str, int]],
    interval: str,
) -> tuple[datetime.datetime, datetime.datetime]:
    diff = date_to - date_from
    new_date_from = date_from - diff
    new_date_to = date_from
    if interval == "hour":
        # Align previous period time range with that of the current period, so that results are comparable day-by-day
        # (since variations based on time of day are major)
        new_date_from = new_date_from.replace(
            hour=date_from.hour, minute=date_from.minute, second=date_from.second, microsecond=date_from.microsecond
        )
        new_date_to = (new_date_from + diff).replace(
            minute=date_to.minute, second=date_to.second, microsecond=date_to.microsecond
        )
    elif interval != "minute":
        # Align previous period time range to same boundaries as current period
        new_date_from = new_date_from.replace(
            hour=date_from.hour, minute=date_from.minute, second=date_from.second, microsecond=date_from.microsecond
        )
        # Handle date_from = -7d, -14d etc. specially
        if (
            interval == "day"
            and date_from_delta_mapping
            and date_from_delta_mapping.get("days", None)
            and date_from_delta_mapping["days"] % 7 == 0
            and not date_to_delta_mapping
        ):
            # KLUDGE: Unfortunately common relative date ranges such as "Last 7 days" (-7d) or "Last 14 days" (-14d)
            # are wrong because they treat the current ongoing day as an _extra_ one. This means that those ranges
            # are in reality, respectively, 8 and 15 days long. So for the common use case of comparing weeks,
            # it's not possible to just use that period length directly - the results for the previous period
            # would be misaligned by a day.
            # The proper fix would be making -7d actually 7 days, but that requires careful consideration.
            # As a quick fix for the most common week-by-week case, we just always add a day to counteract the woes
            # of relative date ranges:
            new_date_from += datetime.timedelta(days=1)
        new_date_to = (new_date_from + diff).replace(
            hour=date_to.hour, minute=date_to.minute, second=date_to.second, microsecond=date_to.microsecond
        )
    return new_date_from, new_date_to


def generate_cache_key(stringified: str) -> str:
    return "cache_" + hashlib.md5(stringified.encode("utf-8")).hexdigest()


def get_celery_heartbeat() -> Union[str, int]:
    last_heartbeat = get_client().get("POSTHOG_HEARTBEAT")
    worker_heartbeat = int(time.time()) - int(last_heartbeat) if last_heartbeat else -1

    if 0 <= worker_heartbeat < 300:
        return worker_heartbeat
    return "offline"


def base64_decode(data):
    """
    Decodes base64 bytes into string taking into account necessary transformations to match client libraries.
    """
    if isinstance(data, str):
        data = data.encode("ascii")

    # Check if the data is URL-encoded
    if data.startswith(b"data="):
        data = unquote(data.decode("ascii")).split("=", 1)[1]
        data = data.encode("ascii")
    else:
        # If it's not starting with 'data=', it might be just URL-encoded,
        data = unquote(data.decode("ascii")).encode("ascii")

    # Remove any whitespace and add padding if necessary
    data = data.replace(b" ", b"")
    missing_padding = len(data) % 4
    if missing_padding:
        data += b"=" * (4 - missing_padding)

    decoded = base64.b64decode(data)
    return decoded.decode("utf-8", "surrogatepass")


def decompress(data: Any, compression: str):
    if not data:
        return None

    if compression in ("gzip", "gzip-js"):
        if data == b"undefined":
            raise RequestParsingError(
                "data being loaded from the request body for decompression is the literal string 'undefined'"
            )

        try:
            data = gzip.decompress(data)
        except (EOFError, OSError, zlib.error) as error:
            raise RequestParsingError("Failed to decompress data. {}".format(str(error)))

    if compression == "lz64":
        KLUDGES_COUNTER.labels(kludge="lz64_compression").inc()
        if not isinstance(data, str):
            data = data.decode()
        data = data.replace(" ", "+")

        data = lzstring.LZString().decompressFromBase64(data)

        if not data:
            raise RequestParsingError("Failed to decompress data.")

        data = data.encode("utf-16", "surrogatepass").decode("utf-16")

    # Attempt base64 decoding after decompression
    try:
        base64_decoded = base64_decode(data)
        KLUDGES_COUNTER.labels(kludge=f"base64_after_decompression_{compression}").inc()
        data = base64_decoded
    except Exception:
        pass

    try:
        # Use custom parse_constant to handle NaN, Infinity, etc.
        data = json.loads(data, parse_constant=lambda x: None)
    except (json.JSONDecodeError, UnicodeDecodeError) as error_main:
        if compression == "":
            try:
                # Attempt gzip decompression as fallback for unspecified compression
                fallback = decompress(data, "gzip")
                KLUDGES_COUNTER.labels(kludge="unspecified_gzip_fallback").inc()
                return fallback
            except Exception:
                # Increment a separate counter for JSON parsing failures after all decompression attempts
                # We do this because we're no longer tracking these fallbacks in error tracking (since they're not actionable defects),
                # but we still want to know how often they occur.
                KLUDGES_COUNTER.labels(kludge="json_parse_failure_after_unspecified_gzip_fallback").inc()
                raise UnspecifiedCompressionFallbackParsingError(f"Invalid JSON: {error_main}")
        else:
            raise RequestParsingError(f"Invalid JSON: {error_main}")

    # TODO: data can also be an array, function assumes it's either None or a dictionary.
    return data


# Used by non-DRF endpoints from capture.py and decide.py (/decide, /batch, /capture, etc)
def load_data_from_request(request):
    if request.method == "POST":
        if request.content_type in ["", "text/plain", "application/json"]:
            data = request.body
        else:
            data = request.POST.get("data")
    else:
        data = request.GET.get("data")
        if data:
            KLUDGES_COUNTER.labels(kludge="data_in_get_param").inc()

    # add the data in the scope in case there's an exception
    with posthoganalytics.new_context():
        if isinstance(data, dict):
            posthoganalytics.tag("data", data)
        posthoganalytics.tag(
            "origin",
            request.headers.get("origin", request.headers.get("remote_host", "unknown")),
        )
        posthoganalytics.tag("referer", request.headers.get("referer", "unknown"))
        # since version 1.20.0 posthog-js adds its version to the `ver` query parameter as a debug signal here
        posthoganalytics.tag("library.version", request.GET.get("ver", "unknown"))

        compression = (
            request.GET.get("compression")
            or request.POST.get("compression")
            or request.headers.get("content-encoding", "")
        ).lower()

        return decompress(data, compression)


class SingletonDecorator:
    def __init__(self, klass):
        self.klass = klass
        self.instance = None

    def __call__(self, *args, **kwds):
        if self.instance is None:
            self.instance = self.klass(*args, **kwds)
        return self.instance


def get_machine_id() -> str:
    """A MAC address-dependent ID. Useful for PostHog instance analytics."""
    # MAC addresses are 6 bits long, so overflow shouldn't happen
    # hashing here as we don't care about the actual address, just it being rather consistent
    return hashlib.md5(uuid.getnode().to_bytes(6, "little")).hexdigest()


def get_table_size(table_name) -> str:
    from django.db import connection

    query = (
        f'SELECT pg_size_pretty(pg_total_relation_size(relid)) AS "size" '
        f"FROM pg_catalog.pg_statio_user_tables "
        f"WHERE relname = '{table_name}'"
    )
    cursor = connection.cursor()
    cursor.execute(query)
    return dict_from_cursor_fetchall(cursor)[0]["size"]


def get_table_approx_count(table_name) -> str:
    from django.db import connection

    query = f"SELECT reltuples::BIGINT as \"approx_count\" FROM pg_class WHERE relname = '{table_name}'"
    cursor = connection.cursor()
    cursor.execute(query)
    return compact_number(dict_from_cursor_fetchall(cursor)[0]["approx_count"])


def compact_number(value: Union[int, float]) -> str:
    """Return a number in a compact format, with a SI suffix if applicable.
    Client-side equivalent: utils.tsx#compactNumber.
    """
    value = float(f"{value:.3g}")
    magnitude = 0
    while abs(value) >= 1000:
        magnitude += 1
        value /= 1000.0
    return f"{value:f}".rstrip("0").rstrip(".") + ["", "K", "M", "B", "T", "P", "E", "Z", "Y"][magnitude]


def is_postgres_alive() -> bool:
    from posthog.models import User

    try:
        User.objects.count()
        return True
    except DatabaseError:
        return False


def is_redis_alive() -> bool:
    try:
        get_redis_info()
        return True
    except BaseException:
        return False


def is_celery_alive() -> bool:
    try:
        return get_celery_heartbeat() != "offline"
    except BaseException:
        return False


def is_plugin_server_alive() -> bool:
    try:
        from posthog.plugins.plugin_server_api import get_plugin_server_status

        plugin_server_status = get_plugin_server_status()
        return plugin_server_status.status_code == 200
    except BaseException:
        return False


def get_plugin_server_job_queues() -> Optional[list[str]]:
    cache_key_value = get_client().get("@posthog-plugin-server/enabled-job-queues")
    if cache_key_value:
        qs = cache_key_value.decode("utf-8").replace('"', "")
        return qs.split(",")
    return None


def is_object_storage_available() -> bool:
    from posthog.storage import object_storage

    try:
        if settings.OBJECT_STORAGE_ENABLED:
            return object_storage.health_check()
        else:
            return False
    except BaseException:
        return False


def get_redis_info() -> Mapping[str, Any]:
    return get_client().info()


def get_redis_queue_depth() -> int:
    return get_client().llen("celery")


def get_instance_realm() -> str:
    """
    Returns the realm for the current instance. `cloud` or 'demo' or `hosted-clickhouse`.

    Historically this would also have returned `hosted` for hosted postgresql based installations
    """
    if is_cloud():
        return "cloud"
    elif settings.DEMO:
        return "demo"
    else:
        return "hosted-clickhouse"


def get_instance_region() -> Optional[str]:
    """
    Returns the region for the current Cloud instance. `US` or `EU`.
    """
    return settings.CLOUD_DEPLOYMENT


def get_can_create_org(user: Union["AbstractBaseUser", "AnonymousUser"]) -> bool:
    """Returns whether a new organization can be created in the current instance.

    Organizations can be created only in the following cases:
    - if on PostHog Cloud
    - if running end-to-end tests
    - if there's no organization yet
    - if DEBUG is True
    - if an appropriate license is active and MULTI_ORG_ENABLED is True
    """
    from posthog.models.organization import Organization

    if (
        is_cloud()  # There's no limit of organizations on Cloud
        or (settings.DEMO and user.is_anonymous)  # Demo users can have a single demo org, but not more
        or settings.E2E_TESTING
        or settings.DEBUG
        or not Organization.objects.filter(for_internal_metrics=False).exists()  # Definitely can create an org if zero
    ):
        return True

    if settings.MULTI_ORG_ENABLED:
        license = get_cached_instance_license()
        if license is not None and AvailableFeature.ZAPIER in license.available_features:
            return True
        else:
            logger.warning("You have configured MULTI_ORG_ENABLED, but not the required premium PostHog plan!")

    return False


def get_instance_available_sso_providers() -> dict[str, bool]:
    """
    Returns a dictionary containing final determination to which SSO providers are available.
    SAML is not included in this method as it can only be configured domain-based and not instance-based (see `OrganizationDomain` for details)
    Validates configuration settings and license validity (if applicable).
    """
    output: dict[str, bool] = {
        "github": bool(settings.SOCIAL_AUTH_GITHUB_KEY and settings.SOCIAL_AUTH_GITHUB_SECRET),
        "gitlab": bool(settings.SOCIAL_AUTH_GITLAB_KEY and settings.SOCIAL_AUTH_GITLAB_SECRET),
        "google-oauth2": False,
    }

    # Get license information
    bypass_license: bool = is_cloud() or settings.DEMO
    license = None
    if not bypass_license:
        try:
            from products.enterprise.backend.models.license import License
        except ImportError:
            pass
        else:
            license = License.objects.first_valid()

    if getattr(settings, "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY", None) and getattr(
        settings,
        "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET",
        None,
    ):
        if bypass_license or (license is not None and AvailableFeature.SOCIAL_SSO in license.available_features):
            output["google-oauth2"] = True
        else:
            logger.warning("You have Google login set up, but not the required license!")

    return output


def flatten(i: Union[list, tuple], max_depth=10) -> Generator:
    for el in i:
        if isinstance(el, list) and max_depth > 0:
            yield from flatten(el, max_depth=max_depth - 1)
        else:
            yield el


def get_daterange(
    start_date: Optional[datetime.datetime],
    end_date: Optional[datetime.datetime],
    frequency: str,
) -> list[Any]:
    """
    Returns list of a fixed frequency Datetime objects between given bounds.

    Parameters:
        start_date: Left bound for generating dates.
        end_date: Right bound for generating dates.
        frequency: Possible options => minute, hour, day, week, month
    """

    delta = DATERANGE_MAP[frequency]

    if not start_date or not end_date:
        return []

    time_range = []
    if frequency != "minute" and frequency != "hour":
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    if frequency == "week":
        start_date -= datetime.timedelta(days=(start_date.weekday() + 1) % 7)
    if frequency != "month":
        while start_date <= end_date:
            time_range.append(start_date)
            start_date += delta
    else:
        if start_date.day != 1:
            start_date = (start_date.replace(day=1)).replace(day=1)
        while start_date <= end_date:
            time_range.append(start_date)
            start_date = (start_date.replace(day=1) + delta).replace(day=1)
    return time_range


def get_safe_cache(cache_key: str):
    try:
        cached_result = cache.get(cache_key)  # cache.get is safe in most cases
        return cached_result
    except Exception:  # if it errors out, the cache is probably corrupted
        try:
            cache.delete(cache_key)  # in that case, try to delete the cache
        except Exception:
            pass
    return None


def is_anonymous_id(distinct_id: str) -> bool:
    # Our anonymous ids are _not_ uuids, but a random collection of strings
    return bool(re.match(ANONYMOUS_REGEX, distinct_id))


def is_valid_regex(value: Any) -> bool:
    try:
        re.compile(value)
        return True
    except re.error:
        return False


def get_absolute_path(to: str) -> str:
    """
    Returns an absolute path in the FS based on posthog/posthog (back-end root folder)
    """
    return os.path.join(__location__, to)


class GenericEmails:
    """
    List of generic emails that we don't want to use to filter out test accounts.
    """

    def __init__(self):
        with open(get_absolute_path("helpers/generic_emails.txt")) as f:
            self.emails = {x.rstrip(): True for x in f}

    def is_generic(self, email: str) -> bool:
        at_location = email.find("@")
        if at_location == -1:
            return False
        return self.emails.get(email[(at_location + 1) :], False)


@lru_cache(maxsize=1)
def get_available_timezones_with_offsets() -> dict[str, float]:
    now = dt.datetime.now()
    result = {}
    for tz in pytz.common_timezones:
        try:
            offset = pytz.timezone(tz).utcoffset(now)
        except Exception:
            offset = pytz.timezone(tz).utcoffset(now + dt.timedelta(hours=2))
        offset_hours = int(offset.total_seconds()) / 3600
        result[tz] = offset_hours
    return result


def refresh_requested_by_client(request: Request) -> bool | str:
    return _request_has_key_set(
        "refresh",
        request,
        allowed_values=[
            "async",
            "blocking",
            "force_async",
            "force_blocking",
            "force_cache",
            "lazy_async",
        ],
    )


def cache_requested_by_client(request: Request) -> bool | str:
    return _request_has_key_set("use_cache", request)


def filters_override_requested_by_client(request: Request, dashboard: Optional["Dashboard"]) -> dict:
    from posthog.auth import SharingAccessTokenAuthentication

    dashboard_filters = dashboard.filters if dashboard else {}
    raw_override = request.query_params.get("filters_override")

    # Security: Don't allow overrides when accessing via sharing tokens
    if not raw_override or isinstance(request.successful_authenticator, SharingAccessTokenAuthentication):
        return dashboard_filters

    try:
        request_filters = json.loads(raw_override)
    except Exception:
        raise serializers.ValidationError({"filters_override": "Invalid JSON passed in filters_override parameter"})

    return {**dashboard_filters, **request_filters}


def variables_override_requested_by_client(
    request: Optional[Request], dashboard: Optional["Dashboard"], variables: list["InsightVariable"]
) -> Optional[dict[str, dict]]:
    from posthog.api.insight_variable import map_stale_to_latest
    from posthog.auth import SharingAccessTokenAuthentication

    dashboard_variables = (dashboard and dashboard.variables) or {}
    raw_override = request.query_params.get("variables_override") if request else None

    # Security: Don't allow overrides when accessing via sharing tokens
    if not raw_override or (request and isinstance(request.successful_authenticator, SharingAccessTokenAuthentication)):
        return map_stale_to_latest(dashboard_variables, variables)

    try:
        request_variables = json.loads(raw_override)
    except Exception:
        raise serializers.ValidationError({"variables_override": "Invalid JSON passed in variables_override parameter"})

    return map_stale_to_latest({**dashboard_variables, **request_variables}, variables)


def tile_filters_override_requested_by_client(request: Request, tile: Optional["DashboardTile"]) -> dict:
    from posthog.auth import SharingAccessTokenAuthentication

    tile_filters = tile.filters_overrides if tile and tile.filters_overrides else {}
    raw_override = request.query_params.get("tile_filters_override")

    # Security: Don't allow overrides when accessing via sharing tokens
    if not raw_override or isinstance(request.successful_authenticator, SharingAccessTokenAuthentication):
        return tile_filters

    try:
        request_filters = json.loads(raw_override)
    except Exception:
        raise serializers.ValidationError(
            {"tile_filters_override": "Invalid JSON passed in tile_filters_override parameter"}
        )

    return {**tile_filters, **request_filters}


def _request_has_key_set(key: str, request: Request, allowed_values: Optional[list[str]] = None) -> bool | str:
    query_param = request.query_params.get(key)
    data_value = request.data.get(key)

    value = query_param if query_param is not None else data_value

    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if str(value).lower() in ["true", "1", "yes", ""]:  # "" means it's set but no value
        return True
    if str(value).lower() in ["false", "0", "no"]:
        return False
    if allowed_values and value in allowed_values:
        assert isinstance(value, str)
        return value
    return False


def str_to_bool(value: Any) -> bool:
    """Return whether the provided string (or any value really) represents true. Otherwise, false.
    Just like plugin server stringToBoolean.
    """
    if not value:
        return False
    return str(value).lower() in ("y", "yes", "t", "true", "on", "1")


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """Safely convert a value to integer, returning default if conversion fails."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def get_helm_info_env() -> dict:
    try:
        return json.loads(os.getenv("HELM_INSTALL_INFO", "{}"))
    except Exception:
        return {}


def format_query_params_absolute_url(
    request: Request,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    offset_alias: Optional[str] = "offset",
    limit_alias: Optional[str] = "limit",
) -> Optional[str]:
    OFFSET_REGEX = re.compile(rf"([&?]{offset_alias}=)(\d+)")
    LIMIT_REGEX = re.compile(rf"([&?]{limit_alias}=)(\d+)")

    url_to_format = request.build_absolute_uri()

    if not url_to_format:
        return None

    if offset:
        if OFFSET_REGEX.search(url_to_format):
            url_to_format = OFFSET_REGEX.sub(rf"\g<1>{offset}", url_to_format)
        else:
            url_to_format = url_to_format + ("&" if "?" in url_to_format else "?") + f"{offset_alias}={offset}"

    if limit:
        if LIMIT_REGEX.search(url_to_format):
            url_to_format = LIMIT_REGEX.sub(rf"\g<1>{limit}", url_to_format)
        else:
            url_to_format = url_to_format + ("&" if "?" in url_to_format else "?") + f"{limit_alias}={limit}"

    return url_to_format


def get_milliseconds_between_dates(d1: dt.datetime, d2: dt.datetime) -> int:
    return abs(int((d1 - d2).total_seconds() * 1000))


def encode_get_request_params(data: dict[str, Any]) -> dict[str, str]:
    return {
        key: encode_value_as_param(value=value)
        for key, value in data.items()
        # NOTE: we cannot encode `None` as a GET parameter, so we simply omit it
        if value is not None
    }


class DataclassJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


def encode_value_as_param(value: Union[str, list, dict, datetime.datetime]) -> str:
    if isinstance(value, list | dict | tuple):
        return json.dumps(value, cls=DataclassJSONEncoder)
    elif isinstance(value, Enum):
        return value.value
    elif isinstance(value, datetime.datetime):
        return value.isoformat()
    else:
        return value


def is_json(val):
    if isinstance(val, int):
        return False

    try:
        int(val)
        return False
    except:
        pass
    try:
        json.loads(val)
    except (ValueError, TypeError):
        return False
    return True


def cast_timestamp_or_now(timestamp: Optional[Union[datetime.datetime, str]]) -> str:
    if not timestamp:
        timestamp = timezone.now()

    # clickhouse specific formatting
    if isinstance(timestamp, str):
        timestamp = parser.isoparse(timestamp)
    else:
        timestamp = timestamp.astimezone(ZoneInfo("UTC"))

    return timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")


def get_crontab(schedule: Optional[str]) -> Optional[crontab]:
    if schedule is None or schedule == "":
        return None

    try:
        minute, hour, day_of_month, month_of_year, day_of_week = schedule.strip().split(" ")
        return crontab(
            minute=minute,
            hour=hour,
            day_of_month=day_of_month,
            month_of_year=month_of_year,
            day_of_week=day_of_week,
        )
    except Exception as err:
        capture_exception(err)
        return None


def generate_short_id():
    """Generate securely random 8 characters long alphanumeric ID."""
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))


def get_week_start_for_country_code(country_code: str) -> int:
    # Data from https://github.com/unicode-cldr/cldr-core/blob/master/supplemental/weekData.json
    if country_code in [
        "AG",
        "AS",
        "AU",
        "BD",
        "BR",
        "BS",
        "BT",
        "BW",
        "BZ",
        "CA",
        "CN",
        "CO",
        "DM",
        "DO",
        "ET",
        "GT",
        "GU",
        "HK",
        "HN",
        "ID",
        "IL",
        "IN",
        "JM",
        "JP",
        "KE",
        "KH",
        "KR",
        "LA",
        "MH",
        "MM",
        "MO",
        "MT",
        "MX",
        "MZ",
        "NI",
        "NP",
        "PA",
        "PE",
        "PH",
        "PK",
        "PR",
        "PT",
        "PY",
        "SA",
        "SG",
        "SV",
        "TH",
        "TT",
        "TW",
        "UM",
        "US",
        "VE",
        "VI",
        "WS",
        "YE",
        "ZA",
        "ZW",
    ]:
        return 0  # Sunday
    if country_code in [
        "AE",
        "AF",
        "BH",
        "DJ",
        "DZ",
        "EG",
        "IQ",
        "IR",
        "JO",
        "KW",
        "LY",
        "OM",
        "QA",
        "SD",
        "SY",
    ]:
        return 6  # Saturday
    return 1  # Monday


def sleep_time_generator() -> Generator[float, None, None]:
    # a generator that yield an exponential back off between 0.1 and 3 seconds
    for _ in range(10):
        yield 0.1  # 1 second in total
    for _ in range(5):
        yield 0.2  # 1 second in total
    for _ in range(5):
        yield 0.4  # 2 seconds in total
    for _ in range(5):
        yield 0.8  # 4 seconds in total
    for _ in range(10):
        yield 1.5  # 15 seconds in total
    while True:
        yield 3.0


@async_to_sync
async def wait_for_parallel_celery_group(task: Any, expires: Optional[datetime.datetime] = None) -> Any:
    """
    Wait for a group of celery tasks to finish, but don't wait longer than max_timeout.
    For parallel tasks, this is the only way to await the entire group.
    """
    default_expires = datetime.timedelta(minutes=5)

    if not expires:
        expires = datetime.datetime.now(tz=datetime.UTC) + default_expires

    sleep_generator = sleep_time_generator()

    while not task.ready():
        if datetime.datetime.now(tz=datetime.UTC) > expires:
            child_states = []
            child: AsyncResult
            children = task.children or []
            for child in children:
                child_states.append(child.state)
                # this child should not be retried...
                if child.state in ["PENDING", "STARTED"]:
                    # terminating here terminates the process not the task
                    # but if the task is in PENDING or STARTED after 10 minutes
                    # we have to assume the celery process isn't processing another task
                    # see: https://docs.celeryq.dev/en/stable/userguide/workers.html#revoke-revoking-tasks
                    # and: https://docs.celeryq.dev/en/latest/reference/celery.result.html
                    # we terminate the process to avoid leaking an instance of Chrome
                    child.revoke(terminate=True)

            logger.error(
                "Timed out waiting for celery task to finish",
                task_id=task.id,
                ready=task.ready(),
                successful=task.successful(),
                failed=task.failed(),
                task_state=task.state,
                child_states=child_states,
                timeout=expires,
            )
            raise TimeoutError("Timed out waiting for celery task to finish")

        await asyncio.sleep(next(sleep_generator))
    return task


def patchable(fn):
    """
    Decorator which allows patching behavior of a function at run-time.
    Supports chaining multiple patches in sequence, where earlier patches
    are applied before later ones.

    Used in benchmarking scripts and tests.
    """

    import posthog

    if not posthog.settings.TEST:
        return fn

    @wraps(fn)
    def inner(*args, **kwargs):
        # Execute patches in sequence: first patch → second patch → ... → original function
        return execute_patch_chain(0, *args, **kwargs)

    # Initialize empty patch list
    inner._patch_list = []  # type: ignore[attr-defined]

    # Function to execute the patch chain starting from a specific index
    def execute_patch_chain(index, *args, **kwargs):
        # If we've gone through all patches, execute the original function
        if index >= len(inner._patch_list):  # type: ignore[attr-defined]
            return fn(*args, **kwargs)

        # Execute the current patch, passing a function that will invoke the next patch
        next_fn = lambda *a, **kw: execute_patch_chain(index + 1, *a, **kw)
        return inner._patch_list[index](next_fn, *args, **kwargs)  # type: ignore[attr-defined]

    inner._execute_patch_chain = execute_patch_chain  # type: ignore[attr-defined]

    def patch(wrapper):
        # Add the wrapper to the end of the patch list
        inner._patch_list.append(wrapper)  # type: ignore[attr-defined]

    def unpatch():
        # Remove the most recent patch if there is one
        if inner._patch_list:  # type: ignore[attr-defined]
            inner._patch_list.pop()  # type: ignore[attr-defined]

    @contextmanager
    def temp_patch(wrapper):
        """
        Context manager for temporary patching. Adds the wrapper to the patch list
        and removes it when the 'with' block exits.
        """
        patch(wrapper)
        try:
            yield
        finally:
            unpatch()

    inner._patch = patch  # type: ignore[attr-defined]
    inner._unpatch = unpatch  # type: ignore[attr-defined]
    inner._temp_patch = temp_patch  # type: ignore[attr-defined]

    return inner


def label_for_team_id_to_track(team_id: int) -> str:
    team_id_filter: list[str] = settings.DECIDE_TRACK_TEAM_IDS

    team_id_as_string = str(team_id)

    if "all" in team_id_filter:
        return team_id_as_string

    if team_id_as_string in team_id_filter:
        return team_id_as_string

    team_id_ranges = [team_id_range for team_id_range in team_id_filter if ":" in team_id_range]
    for range in team_id_ranges:
        try:
            start, end = range.split(":")
            if int(start) <= team_id <= int(end):
                return team_id_as_string
        except Exception:
            pass

    return "unknown"


def camel_to_snake_case(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def multisort(xs: list, specs: tuple[tuple[str, bool], ...]):
    """
    Takes a list and tuples of field and order to sort them on multiple passes. This
    is useful to sort a list by multiple fields where some of them are ordered differently
    than others.

    Example: `multisort(list(student_objects), (('grade', True), ('age', False)))`

    https://docs.python.org/3/howto/sorting.html#sort-stability-and-complex-sorts
    """
    for key, reverse in reversed(specs):
        xs.sort(key=itemgetter(key), reverse=reverse)
    return xs


def get_from_dict_or_attr(obj: Any, key: str):
    if isinstance(obj, dict):
        return obj.get(key, None)
    elif hasattr(obj, key):
        return getattr(obj, key, None)
    else:
        raise AttributeError(f"Object {obj} has no key {key}")


def is_relative_url(url: str | None) -> bool:
    """
    Returns True if `url` is a relative URL (e.g. "/foo/bar" or "/")
    """
    if url is None:
        return False

    parsed = urlparse(url)

    return (
        parsed.scheme == "" and parsed.netloc == "" and parsed.path.startswith("/") and not parsed.path.startswith("//")
    )


def to_json(obj: dict) -> bytes:
    # pydantic doesn't sort keys reliably, so use orjson to serialize to json
    option = orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS
    json_string = orjson.dumps(obj, default=JSONEncoder().default, option=option)

    return json_string


def opt_slash_path(route: str, view: Callable, name: Optional[str] = None) -> URLPattern:
    """Catches path with or without trailing slash, taking into account query param and hash."""
    # Ignoring the type because while name can be optional on re_path, mypy doesn't agree
    return re_path(rf"^{route}/?(?:[?#].*)?$", view, name=name)  # type: ignore


def get_current_user_from_thread() -> Optional["User"]:
    from threading import current_thread

    request = getattr(current_thread(), "request", None)
    if request and hasattr(request, "user"):
        return request.user
    return None
