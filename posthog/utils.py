import base64
import dataclasses
import datetime
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)
from urllib.parse import urljoin, urlparse

import lzstring
import pytz
from celery.schedules import crontab
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.db.utils import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import get_template
from django.utils import timezone
from rest_framework.request import Request
from sentry_sdk import configure_scope
from sentry_sdk.api import capture_exception

from posthog.constants import AvailableFeature
from posthog.exceptions import RequestParsingError
from posthog.redis import get_client

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser, AnonymousUser


DATERANGE_MAP = {
    "minute": datetime.timedelta(minutes=1),
    "hour": datetime.timedelta(hours=1),
    "day": datetime.timedelta(days=1),
    "week": datetime.timedelta(weeks=1),
    "month": datetime.timedelta(days=31),
}
ANONYMOUS_REGEX = r"^([a-z0-9]+\-){4}([a-z0-9]+)$"

# https://stackoverflow.com/questions/4060221/how-to-reliably-open-a-file-in-the-same-directory-as-a-python-script
__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


def format_label_date(date: datetime.datetime, interval: str) -> str:
    labels_format = "%-d-%b-%Y"
    if interval == "hour":
        labels_format += " %H:%M"
    return date.strftime(labels_format)


def absolute_uri(url: Optional[str] = None) -> str:
    """
    Returns an absolutely-formatted URL based on the `SITE_URL` config.
    """
    if not url:
        return settings.SITE_URL
    return urljoin(settings.SITE_URL.rstrip("/") + "/", url.lstrip("/"))


def get_previous_week(at: Optional[datetime.datetime] = None) -> Tuple[datetime.datetime, datetime.datetime]:
    """
    Returns a pair of datetimes, representing the start and end of the week preceding to the passed date's week.
    `at` is the datetime to use as a reference point.
    """

    if not at:
        at = timezone.now()

    period_end: datetime.datetime = datetime.datetime.combine(
        at - datetime.timedelta(timezone.now().weekday() + 1), datetime.time.max, tzinfo=pytz.UTC,
    )  # very end of the previous Sunday

    period_start: datetime.datetime = datetime.datetime.combine(
        period_end - datetime.timedelta(6), datetime.time.min, tzinfo=pytz.UTC,
    )  # very start of the previous Monday

    return (period_start, period_end)


def get_previous_day(at: Optional[datetime.datetime] = None) -> Tuple[datetime.datetime, datetime.datetime]:
    """
    Returns a pair of datetimes, representing the start and end of the preceding day.
    `at` is the datetime to use as a reference point.
    """

    if not at:
        at = timezone.now()

    period_end: datetime.datetime = datetime.datetime.combine(
        at - datetime.timedelta(days=1), datetime.time.max, tzinfo=pytz.UTC,
    )  # very end of the previous day

    period_start: datetime.datetime = datetime.datetime.combine(
        period_end, datetime.time.min, tzinfo=pytz.UTC,
    )  # very start of the previous day

    return (period_start, period_end)


def relative_date_parse(input: str) -> datetime.datetime:
    try:
        return datetime.datetime.strptime(input, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
    except ValueError:
        pass

    # when input also contains the time for intervals "hour" and "minute"
    # the above try fails. Try one more time from isoformat.
    try:
        return parser.isoparse(input).replace(tzinfo=pytz.UTC)
    except ValueError:
        pass

    regex = r"\-?(?P<number>[0-9]+)?(?P<type>[a-z])(?P<position>Start|End)?"
    match = re.search(regex, input)
    date = timezone.now()
    if not match:
        return date
    if match.group("type") == "h":
        date -= relativedelta(hours=int(match.group("number")))
        return date.replace(minute=0, second=0, microsecond=0)
    elif match.group("type") == "d":
        if match.group("number"):
            date -= relativedelta(days=int(match.group("number")))
    elif match.group("type") == "w":
        if match.group("number"):
            date -= relativedelta(weeks=int(match.group("number")))
    elif match.group("type") == "m":
        if match.group("number"):
            date -= relativedelta(months=int(match.group("number")))
        if match.group("position") == "Start":
            date -= relativedelta(day=1)
        if match.group("position") == "End":
            date -= relativedelta(day=31)
    elif match.group("type") == "y":
        if match.group("number"):
            date -= relativedelta(years=int(match.group("number")))
        if match.group("position") == "Start":
            date -= relativedelta(month=1, day=1)
        if match.group("position") == "End":
            date -= relativedelta(month=12, day=31)
    return date.replace(hour=0, minute=0, second=0, microsecond=0)


def request_to_date_query(filters: Dict[str, Any], exact: Optional[bool]) -> Dict[str, datetime.datetime]:
    if filters.get("date_from"):
        date_from: Optional[datetime.datetime] = relative_date_parse(filters["date_from"])
        if filters["date_from"] == "all":
            date_from = None
    else:
        date_from = datetime.datetime.today() - relativedelta(days=7)
        date_from = date_from.replace(hour=0, minute=0, second=0, microsecond=0)

    date_to = None
    if filters.get("date_to"):
        date_to = relative_date_parse(filters["date_to"])

    resp = {}
    if date_from:
        resp["timestamp__gte"] = date_from.replace(tzinfo=pytz.UTC)
    if date_to:
        days = 1 if not exact else 0
        resp["timestamp__lte"] = (date_to + relativedelta(days=days)).replace(tzinfo=pytz.UTC)
    return resp


def get_git_branch() -> Optional[str]:
    """
    Returns the symbolic name of the current active branch. Will return None in case of failure.
    Example: get_git_branch()
        => "master"
    """

    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--symbolic-full-name", "--abbrev-ref", "HEAD"])
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return None


def get_git_commit() -> Optional[str]:
    """
    Returns the short hash of the last commit.
    Example: get_git_commit()
        => "4ff54c8d"
    """

    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode("utf-8").strip()
    except Exception:
        return None


def get_js_url(request: HttpRequest) -> str:
    """
    As the web app may be loaded from a non-localhost url (e.g. from the worker container calling the web container)
    it is necessary to set the JS_URL host based on the calling origin
    """
    if settings.DEBUG and settings.JS_URL == "http://localhost:8234":
        return f"http://{request.get_host().split(':')[0]}:8234"
    return settings.JS_URL


def render_template(template_name: str, request: HttpRequest, context: Dict = {}) -> HttpResponse:
    from loginas.utils import is_impersonated_session

    template = get_template(template_name)

    context["opt_out_capture"] = os.getenv("OPT_OUT_CAPTURE", False) or is_impersonated_session(request)
    context["self_capture"] = settings.SELF_CAPTURE

    if os.environ.get("SENTRY_DSN"):
        context["sentry_dsn"] = os.environ["SENTRY_DSN"]

    if settings.DEBUG and not settings.TEST:
        context["debug"] = True
        context["git_rev"] = get_git_commit()
        context["git_branch"] = get_git_branch()

    if settings.E2E_TESTING:
        context["e2e_testing"] = True

    if settings.SELF_CAPTURE:
        api_token = get_self_capture_api_token(request)

        if api_token:
            context["js_posthog_api_key"] = f"'{api_token}'"
            context["js_posthog_host"] = "window.location.origin"
    else:
        context["js_posthog_api_key"] = "'sTMFPsFhdP1Ssg'"
        context["js_posthog_host"] = "'https://app.posthog.com'"

    context["js_capture_internal_metrics"] = settings.CAPTURE_INTERNAL_METRICS
    context["js_url"] = get_js_url(request)

    posthog_app_context: Dict[str, Any] = {
        "persisted_feature_flags": settings.PERSISTED_FEATURE_FLAGS,
        "anonymous": not request.user or not request.user.is_authenticated,
    }

    # Set the frontend app context
    if not request.GET.get("no-preloaded-app-context"):
        from posthog.api.team import TeamSerializer
        from posthog.api.user import User, UserSerializer
        from posthog.views import preflight_check

        posthog_app_context = {
            "current_user": None,
            "current_team": None,
            "preflight": json.loads(preflight_check(request).getvalue()),
            "default_event_name": get_default_event_name(),
            "switched_team": getattr(request, "switched_team", None),
            **posthog_app_context,
        }

        if request.user.pk:
            user_serialized = UserSerializer(request.user, context={"request": request}, many=False)
            posthog_app_context["current_user"] = user_serialized.data
            team = cast(User, request.user).team
            if team:
                team_serialized = TeamSerializer(team, context={"request": request}, many=False)
                posthog_app_context["current_team"] = team_serialized.data
                posthog_app_context["frontend_apps"] = get_frontend_apps(team.pk)

    context["posthog_app_context"] = json.dumps(posthog_app_context, default=json_uuid_convert)

    html = template.render(context, request=request)
    return HttpResponse(html)


def get_self_capture_api_token(request: Optional[HttpRequest]) -> Optional[str]:
    from posthog.models import Team

    # Get the current user's team (or first team in the instance) to set self capture configs
    team: Optional[Team] = None
    if request and getattr(request, "user", None) and getattr(request.user, "team", None):
        team = request.user.team  # type: ignore
    else:
        try:
            team = Team.objects.only("api_token").first()
        except Exception:
            pass

    if team:
        return team.api_token
    return None


def get_default_event_name():
    from posthog.models import EventDefinition

    if EventDefinition.objects.filter(name="$pageview").exists():
        return "$pageview"
    elif EventDefinition.objects.filter(name="$screen").exists():
        return "$screen"
    return "$pageview"


def get_frontend_apps(team_id: int) -> Dict[int, Dict[str, Any]]:
    from posthog.models import Plugin, PluginSourceFile

    plugin_configs = (
        Plugin.objects.filter(pluginconfig__team_id=team_id, pluginconfig__enabled=True)
        .filter(pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED, pluginsourcefile__filename="frontend.tsx")
        .values("pluginconfig__id", "pluginconfig__config", "config_schema", "id", "plugin_type", "name")
        .all()
    )

    frontend_apps = {}
    for p in plugin_configs:
        config = p["pluginconfig__config"] or {}
        config_schema = p["config_schema"] or {}
        secret_fields = set([field["key"] for field in config_schema if "secret" in field and field["secret"]])
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
    date_from: datetime.datetime, date_to: datetime.datetime,
) -> Tuple[datetime.datetime, datetime.datetime]:
    new_date_to = date_from
    diff = date_to - date_from
    new_date_from = date_from - diff
    return new_date_from, new_date_to


def cors_response(request, response):
    if not request.META.get("HTTP_ORIGIN"):
        return response
    url = urlparse(request.META["HTTP_ORIGIN"])
    response["Access-Control-Allow-Origin"] = f"{url.scheme}://{url.netloc}"
    response["Access-Control-Allow-Credentials"] = "true"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"

    # Handle headers that sentry randomly sends for every request.
    #  Would cause a CORS failure otherwise.
    allow_headers = request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS", "").split(",")
    allow_headers = [header for header in allow_headers if header in ["traceparent", "request-id"]]

    response["Access-Control-Allow-Headers"] = "X-Requested-With" + (
        "," + ",".join(allow_headers) if len(allow_headers) > 0 else ""
    )
    return response


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
    if not isinstance(data, str):
        data = data.decode()

    data = base64.b64decode(data.replace(" ", "+") + "===")

    return data.decode("utf8", "surrogatepass").encode("utf-16", "surrogatepass")


def decompress(data: Any, compression: str):
    if not data:
        return None

    if compression == "gzip" or compression == "gzip-js":
        if data == b"undefined":
            raise RequestParsingError(
                "data being loaded from the request body for decompression is the literal string 'undefined'"
            )

        try:
            data = gzip.decompress(data)
        except (EOFError, OSError) as error:
            raise RequestParsingError("Failed to decompress data. %s" % (str(error)))

    if compression == "lz64":
        if not isinstance(data, str):
            data = data.decode()
        data = data.replace(" ", "+")

        data = lzstring.LZString().decompressFromBase64(data)

        if not data:
            raise RequestParsingError("Failed to decompress data.")

        data = data.encode("utf-16", "surrogatepass").decode("utf-16")

    base64_decoded = None
    try:
        base64_decoded = base64_decode(data)
    except Exception:
        pass

    if base64_decoded:
        data = base64_decoded

    try:
        # parse_constant gets called in case of NaN, Infinity etc
        # default behaviour is to put those into the DB directly
        # but we just want it to return None
        data = json.loads(data, parse_constant=lambda x: None)
    except (json.JSONDecodeError, UnicodeDecodeError) as error_main:
        if compression == "":
            try:
                return decompress(data, "gzip")
            except Exception as inner:
                # re-trying with compression set didn't succeed, throw original error
                raise RequestParsingError("Invalid JSON: %s" % (str(error_main))) from inner
        else:
            raise RequestParsingError("Invalid JSON: %s" % (str(error_main)))

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

    # add the data in sentry's scope in case there's an exception
    with configure_scope() as scope:
        scope.set_context("data", data)
        scope.set_tag("origin", request.headers.get("origin", request.headers.get("remote_host", "unknown")))
        scope.set_tag("referer", request.headers.get("referer", "unknown"))
        # since version 1.20.0 posthog-js adds its version to the `ver` query parameter as a debug signal here
        scope.set_tag("library.version", request.GET.get("ver", "unknown"))

    compression = (
        request.GET.get("compression") or request.POST.get("compression") or request.headers.get("content-encoding", "")
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
        ping = get_client().get("@posthog-plugin-server/ping")
        return bool(ping and parser.isoparse(ping) > timezone.now() - relativedelta(seconds=30))
    except BaseException:
        return False


def get_plugin_server_version() -> Optional[str]:
    cache_key_value = get_client().get("@posthog-plugin-server/version")
    if cache_key_value:
        return cache_key_value.decode("utf-8")
    return None


def get_plugin_server_job_queues() -> Optional[List[str]]:
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
    if settings.MULTI_TENANCY:
        return "cloud"
    elif settings.DEMO:
        return "demo"
    else:
        return "hosted-clickhouse"


def get_can_create_org(user: Union["AbstractBaseUser", "AnonymousUser"]) -> bool:
    """Returns whether a new organization can be created in the current instance.

    Organizations can be created only in the following cases:
    - if on PostHog Cloud
    - if running end-to-end tests
    - if there's no organization yet
    - if an appropriate license is active and MULTI_ORG_ENABLED is True
    """
    from posthog.models.organization import Organization

    if (
        settings.MULTI_TENANCY  # There's no limit of organizations on Cloud
        or (settings.DEMO and user.is_anonymous)  # Demo users can have a single demo org, but not more
        or settings.E2E_TESTING
        or not Organization.objects.filter(for_internal_metrics=False).exists()  # Definitely can create an org if zero
    ):
        return True

    if settings.MULTI_ORG_ENABLED:
        try:
            from ee.models.license import License
        except ImportError:
            pass
        else:
            license = License.objects.first_valid()
            if license is not None and AvailableFeature.ZAPIER in license.available_features:
                return True
            else:
                print_warning(["You have configured MULTI_ORG_ENABLED, but not the required premium PostHog plan!"])

    return False


def get_instance_available_sso_providers() -> Dict[str, bool]:
    """
    Returns a dictionary containing final determination to which SSO providers are available.
    SAML is not included in this method as it can only be configured domain-based and not instance-based (see `OrganizationDomain` for details)
    Validates configuration settings and license validity (if applicable).
    """
    output: Dict[str, bool] = {
        "github": bool(settings.SOCIAL_AUTH_GITHUB_KEY and settings.SOCIAL_AUTH_GITHUB_SECRET),
        "gitlab": bool(settings.SOCIAL_AUTH_GITLAB_KEY and settings.SOCIAL_AUTH_GITLAB_SECRET),
        "google-oauth2": False,
    }

    # Get license information
    bypass_license: bool = settings.MULTI_TENANCY
    license = None
    try:
        from ee.models.license import License
    except ImportError:
        pass
    else:
        license = License.objects.first_valid()

    if getattr(settings, "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY", None) and getattr(
        settings, "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET", None,
    ):
        if bypass_license or (license is not None and AvailableFeature.GOOGLE_LOGIN in license.available_features):
            output["google-oauth2"] = True
        else:
            print_warning(["You have Google login set up, but not the required license!"])

    return output


def flatten(i: Union[List, Tuple]) -> Generator:
    for el in i:
        if isinstance(el, list):
            yield from flatten(el)
        else:
            yield el


def get_daterange(
    start_date: Optional[datetime.datetime], end_date: Optional[datetime.datetime], frequency: str
) -> List[Any]:
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


def mask_email_address(email_address: str) -> str:
    """
    Grabs an email address and returns it masked in a human-friendly way to protect PII.
        Example: testemail@posthog.com -> t********l@posthog.com
    """
    index = email_address.find("@")

    if index == -1:
        raise ValueError("Please provide a valid email address.")

    if index == 1:
        # Username is one letter, mask it differently
        return f"*{email_address[index:]}"

    return f"{email_address[0]}{'*' * (index - 2)}{email_address[index-1:]}"


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
        with open(get_absolute_path("helpers/generic_emails.txt"), "r") as f:
            self.emails = {x.rstrip(): True for x in f}

    def is_generic(self, email: str) -> bool:
        at_location = email.find("@")
        if at_location == -1:
            return False
        return self.emails.get(email[(at_location + 1) :], False)


def get_available_timezones_with_offsets() -> Dict[str, float]:
    now = dt.datetime.now()
    result = {}
    for tz in pytz.common_timezones:
        try:
            offset = pytz.timezone(tz).utcoffset(now)
        except Exception:
            offset = pytz.timezone(tz).utcoffset(now + dt.timedelta(hours=2))
        if offset is None:
            continue
        offset_hours = int(offset.total_seconds()) / 3600
        result[tz] = offset_hours
    return result


def should_refresh(request: Request) -> bool:
    query_param = request.query_params.get("refresh")
    data_value = request.data.get("refresh")

    return (query_param is not None and (query_param == "" or query_param.lower() == "true")) or data_value is True


def str_to_bool(value: Any) -> bool:
    """Return whether the provided string (or any value really) represents true. Otherwise false.
    Just like plugin server stringToBoolean.
    """
    if not value:
        return False
    return str(value).lower() in ("y", "yes", "t", "true", "on", "1")


def print_warning(warning_lines: Sequence[str]):
    highlight_length = min(max(map(len, warning_lines)) // 2, shutil.get_terminal_size().columns)
    print(
        "\n".join(("", "🔻" * highlight_length, *warning_lines, "🔺" * highlight_length, "",)), file=sys.stderr,
    )


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
    OFFSET_REGEX = re.compile(fr"([&?]{offset_alias}=)(\d+)")
    LIMIT_REGEX = re.compile(fr"([&?]{limit_alias}=)(\d+)")

    url_to_format = request.build_absolute_uri()

    if not url_to_format:
        return None

    if offset:
        if OFFSET_REGEX.search(url_to_format):
            url_to_format = OFFSET_REGEX.sub(fr"\g<1>{offset}", url_to_format)
        else:
            url_to_format = url_to_format + ("&" if "?" in url_to_format else "?") + f"{offset_alias}={offset}"

    if limit:
        if LIMIT_REGEX.search(url_to_format):
            url_to_format = LIMIT_REGEX.sub(fr"\g<1>{limit}", url_to_format)
        else:
            url_to_format = url_to_format + ("&" if "?" in url_to_format else "?") + f"{limit_alias}={limit}"

    return url_to_format


def get_milliseconds_between_dates(d1: dt.datetime, d2: dt.datetime) -> int:
    return abs(int((d1 - d2).total_seconds() * 1000))


def encode_get_request_params(data: Dict[str, Any]) -> Dict[str, str]:
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
    if isinstance(value, (list, dict, tuple)):
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


def cast_timestamp_or_now(timestamp: Optional[Union[timezone.datetime, str]]) -> str:
    if not timestamp:
        timestamp = timezone.now()

    # clickhouse specific formatting
    if isinstance(timestamp, str):
        timestamp = parser.isoparse(timestamp)
    else:
        timestamp = timestamp.astimezone(pytz.utc)

    return timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")


def get_crontab(schedule: Optional[str]) -> Optional[crontab]:
    if schedule is None or schedule == "":
        return None

    try:
        minute, hour, day_of_month, month_of_year, day_of_week = schedule.strip().split(" ")
        return crontab(
            minute=minute, hour=hour, day_of_month=day_of_month, month_of_year=month_of_year, day_of_week=day_of_week,
        )
    except Exception as err:
        capture_exception(err)
        return None
