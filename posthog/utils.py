import base64
import datetime
import gzip
import hashlib
import json
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse, urlsplit

import lzstring  # type: ignore
import pytz
import redis
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest, HttpResponse
from django.template.loader import get_template
from django.utils import timezone
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from sentry_sdk import push_scope


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
        date = date - relativedelta(hours=int(match.group("number")))
        return date.replace(minute=0, second=0, microsecond=0)
    elif match.group("type") == "d":
        if match.group("number"):
            date = date - relativedelta(days=int(match.group("number")))
    elif match.group("type") == "m":
        if match.group("number"):
            date = date - relativedelta(months=int(match.group("number")))
        if match.group("position") == "Start":
            date = date - relativedelta(day=1)
        if match.group("position") == "End":
            date = date - relativedelta(day=31)
    elif match.group("type") == "y":
        if match.group("number"):
            date = date - relativedelta(years=int(match.group("number")))
        if match.group("position") == "Start":
            date = date - relativedelta(month=1, day=1)
        if match.group("position") == "End":
            date = date - relativedelta(month=12, day=31)
    return date.replace(hour=0, minute=0, second=0, microsecond=0)


def request_to_date_query(filters: Dict[str, Any], exact: Optional[bool]) -> Dict[str, datetime.datetime]:
    if filters.get("date_from"):
        date_from = relative_date_parse(filters["date_from"])
        if filters["date_from"] == "all":
            date_from = None  # type: ignore
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


def render_template(template_name: str, request: HttpRequest, context=None) -> HttpResponse:
    from posthog.models import Team

    if context is None:
        context = {}
    template = get_template(template_name)
    try:
        context["opt_out_capture"] = request.user.team_set.get().opt_out_capture
    except (Team.DoesNotExist, AttributeError):
        team = Team.objects.all()
        # if there's one team on the instance, and they've set opt_out
        # we'll opt out anonymous users too
        if team.count() == 1:
            context["opt_out_capture"] = (team.first().opt_out_capture,)  # type: ignore

    if os.environ.get("OPT_OUT_CAPTURE"):
        context["opt_out_capture"] = True

    if os.environ.get("SOCIAL_AUTH_GITHUB_KEY") and os.environ.get("SOCIAL_AUTH_GITHUB_SECRET"):
        context["github_auth"] = True

    if os.environ.get("SOCIAL_AUTH_GITLAB_KEY") and os.environ.get("SOCIAL_AUTH_GITLAB_SECRET"):
        context["gitlab_auth"] = True

    if os.environ.get("SENTRY_DSN"):
        context["sentry_dsn"] = os.environ["SENTRY_DSN"]

    if settings.DEBUG and not settings.TEST:
        context["debug"] = True
        try:
            context["git_rev"] = (
                subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode("ascii").strip()
            )
        except:
            context["git_rev"] = None
        try:
            context["git_branch"] = (
                subprocess.check_output(["git", "rev-parse", "--symbolic-full-name", "--abbrev-ref", "HEAD"])
                .decode("ascii")
                .strip()
            )
        except:
            context["git_branch"] = None

    html = template.render(context, request=request)
    return HttpResponse(html)


def friendly_time(seconds: float):
    minutes, seconds = divmod(seconds, 60.0)
    hours, minutes = divmod(minutes, 60.0)
    return "{hours}{minutes}{seconds}".format(
        hours="{h} hours ".format(h=int(hours)) if hours > 0 else "",
        minutes="{m} minutes ".format(m=int(minutes)) if minutes > 0 else "",
        seconds="{s} seconds".format(s=int(seconds)) if seconds > 0 or (minutes == 0 and hours == 0) else "",
    ).strip()


def append_data(dates_filled: List, interval=None, math="sum") -> Dict:
    append: Dict[str, Any] = {}
    append["data"] = []
    append["labels"] = []
    append["days"] = []

    labels_format = "%a. %-d %B"
    days_format = "%Y-%m-%d"

    if interval == "hour" or interval == "minute":
        labels_format += ", %H:%M"
        days_format += " %H:%M:%S"

    for item in dates_filled:
        date = item[0]
        value = item[1]
        append["days"].append(date.strftime(days_format))
        append["labels"].append(date.strftime(labels_format))
        append["data"].append(value)
    if math == "sum":
        append["count"] = sum(append["data"])
    return append


def get_ip_address(request: HttpRequest) -> str:
    """ use requestobject to fetch client machine's IP Address """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")  ### Real IP address of client Machine
    return ip


def dict_from_cursor_fetchall(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def convert_property_value(input: Union[str, bool, dict, list, int]) -> str:
    if isinstance(input, bool):
        if input == True:
            return "true"
        return "false"
    if isinstance(input, dict) or isinstance(input, list):
        return json.dumps(input, sort_keys=True)
    return str(input)


def get_compare_period_dates(
    date_from: datetime.datetime, date_to: datetime.datetime
) -> Tuple[datetime.datetime, datetime.datetime]:
    new_date_to = date_from
    diff = date_to - date_from
    new_date_from = date_from - diff
    return new_date_from, new_date_to


def cors_response(request, response):
    if not request.META.get("HTTP_ORIGIN"):
        return response
    url = urlparse(request.META["HTTP_ORIGIN"])
    response["Access-Control-Allow-Origin"] = "%s://%s" % (url.scheme, url.netloc)
    response["Access-Control-Allow-Credentials"] = "true"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "X-Requested-With"
    return response


class PersonalAPIKeyAuthentication(authentication.BaseAuthentication):
    """A way of authenticating with personal API keys.

    Only the first key candidate found in the request is tried, and the order is:
    1. Request Authorization header of type Bearer.
    2. Request body.
    3. Request query string.
    """

    keyword = "Bearer"

    def find_key(
        self, request: Union[HttpRequest, Request], extra_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[str, str]]:
        if "HTTP_AUTHORIZATION" in request.META:
            authorization_match = re.match(fr"^{self.keyword}\s+(\S.+)$", request.META["HTTP_AUTHORIZATION"])
            if authorization_match:
                return authorization_match.group(1).strip(), "Authorization header"
        if isinstance(request, Request):
            data = request.data
        else:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = {}
        if "personal_api_key" in data:
            return data["personal_api_key"], "body"
        if "personal_api_key" in request.GET:
            return request.GET["personal_api_key"], "query string"
        if extra_data and "personal_api_key" in extra_data:
            # compatibility with /capture endpoint
            return extra_data["personal_api_key"], "query string data"
        return None

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[Tuple[Any, None]]:
        personal_api_key_with_source = self.find_key(request)
        if not personal_api_key_with_source:
            return None
        personal_api_key, source = personal_api_key_with_source
        PersonalAPIKey = apps.get_model(app_label="posthog", model_name="PersonalAPIKey")
        try:
            personal_api_key_object = (
                PersonalAPIKey.objects.select_related("user").filter(user__is_active=True).get(value=personal_api_key)
            )
        except PersonalAPIKey.DoesNotExist:
            raise AuthenticationFailed(detail=f"Personal API key found in request {source} is invalid.")
        personal_api_key_object.last_used_at = timezone.now()
        personal_api_key_object.save()
        return personal_api_key_object.user, None

    def authenticate_header(self, request) -> str:
        return self.keyword


class TemporaryTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: Request):
        # if the Origin is different, the only authentication method should be temporary_token
        # This happens when someone is trying to create actions from the editor on their own website
        if (
            request.headers.get("Origin")
            and urlsplit(request.headers["Origin"]).netloc not in urlsplit(request.build_absolute_uri("/")).netloc
        ):
            if not request.GET.get("temporary_token"):
                raise AuthenticationFailed(
                    detail="No temporary_token set. "
                    + "That means you're either trying to access this API from a different site, "
                    + "or it means your proxy isn't sending the correct headers. "
                    + "See https://posthog.com/docs/deployment/running-behind-proxy for more information."
                )
        if request.GET.get("temporary_token"):
            User = apps.get_model(app_label="posthog", model_name="User")
            user = User.objects.filter(temporary_token=request.GET.get("temporary_token"))
            if not user.exists():
                raise AuthenticationFailed(detail="User doesnt exist")
            return (user.first(), None)
        return None


class PublicTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: Request):
        if request.GET.get("share_token") and request.parser_context and request.parser_context.get("kwargs"):
            Dashboard = apps.get_model(app_label="posthog", model_name="Dashboard")
            dashboard = Dashboard.objects.filter(
                share_token=request.GET.get("share_token"), pk=request.parser_context["kwargs"].get("pk"),
            )
            if not dashboard.exists():
                raise AuthenticationFailed(detail="Dashboard doesn't exist")
            return (AnonymousUser(), None)
        return None


def generate_cache_key(stringified: str) -> str:
    return "cache_" + hashlib.md5(stringified.encode("utf-8")).hexdigest()


def get_redis_heartbeat() -> Union[str, int]:

    if settings.REDIS_URL:
        redis_instance = redis.from_url(settings.REDIS_URL, db=0)
    else:
        return "offline"

    last_heartbeat = redis_instance.get("POSTHOG_HEARTBEAT") if redis_instance else None
    worker_heartbeat = int(time.time()) - int(last_heartbeat) if last_heartbeat else None

    if worker_heartbeat and (worker_heartbeat == 0 or worker_heartbeat < 300):
        return worker_heartbeat
    return "offline"


def base64_to_json(data) -> Dict:
    return json.loads(
        base64.b64decode(data.replace(" ", "+") + "===")
        .decode("utf8", "surrogatepass")
        .encode("utf-16", "surrogatepass")
    )


# Used by non-DRF endpoins from capture.py and decide.py  (/decide, /batch, /capture, etc)
def load_data_from_request(request) -> Optional[Union[Dict[str, Any], List]]:
    if request.method == "POST":
        if request.content_type == "application/json":
            data = request.body
        else:
            data = request.POST.get("data")
    else:
        data = request.GET.get("data")
    if not data:
        return None

    # add the data in sentry's scope in case there's an exception
    with push_scope() as scope:
        scope.set_context("data", data)

    compression = (
        request.GET.get("compression") or request.POST.get("compression") or request.headers.get("content-encoding", "")
    )
    compression = compression.lower()

    if compression == "gzip":
        data = gzip.decompress(data)

    if compression == "lz64":
        if isinstance(data, str):
            data = lzstring.LZString().decompressFromBase64(data.replace(" ", "+"))
        else:
            data = lzstring.LZString().decompressFromBase64(data.decode().replace(" ", "+"))

    #  Is it plain json?
    try:
        data = json.loads(data)
    except json.JSONDecodeError:
        # if not, it's probably base64 encoded from other libraries
        data = base64_to_json(data)
    # FIXME: data can also be an array, function assumes it's either None or a dictionary.
    return data


def get_token_from_personal_api_key(request, data) -> Tuple[Optional[str], bool]:
    personal_api_key_with_source = PersonalAPIKeyAuthentication().find_key(
        request, data if isinstance(data, dict) else None
    )
    if personal_api_key_with_source:
        token = personal_api_key_with_source[0]
    is_personal_api_key = True
    return (token, is_personal_api_key)
