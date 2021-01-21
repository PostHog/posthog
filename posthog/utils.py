import base64
import datetime
import gzip
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from itertools import count
from typing import (
    Any,
    Dict,
    Generator,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)
from urllib.parse import urljoin, urlparse

import lzstring
import pytz
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models.query import QuerySet
from django.db.utils import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import get_template
from django.utils import timezone
from rest_framework.exceptions import APIException
from sentry_sdk import capture_exception, push_scope

from posthog.redis import get_client
from posthog.settings import print_warning

DATERANGE_MAP = {
    "minute": datetime.timedelta(minutes=1),
    "hour": datetime.timedelta(hours=1),
    "day": datetime.timedelta(days=1),
    "week": datetime.timedelta(weeks=1),
    "month": datetime.timedelta(days=31),
}


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


def exception_reporting(exception: BaseException, context: Dict) -> None:
    """
    Determines which exceptions to report to Sentry and sends them.
    """
    if not isinstance(exception, APIException):
        capture_exception(exception)


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


def render_template(template_name: str, request: HttpRequest, context: Dict = {}) -> HttpResponse:
    from posthog.models import Team

    template = get_template(template_name)

    # Get the current user's team (or first team in the instance) to set opt out capture & self capture configs
    team: Optional[Team] = None
    try:
        team = request.user.team  # type: ignore
    except (Team.DoesNotExist, AttributeError):
        team = Team.objects.first()

    if os.environ.get("OPT_OUT_CAPTURE"):
        # Prioritise instance-level config
        context["opt_out_capture"] = True
    else:
        context["opt_out_capture"] = team.opt_out_capture if team else False

    if settings.SOCIAL_AUTH_GITHUB_KEY and settings.SOCIAL_AUTH_GITHUB_SECRET:
        context["github_auth"] = True
    if settings.SOCIAL_AUTH_GITLAB_KEY and settings.SOCIAL_AUTH_GITLAB_SECRET:
        context["gitlab_auth"] = True
    if getattr(settings, "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY", None) and getattr(
        settings, "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET", None
    ):
        if settings.MULTI_TENANCY:
            context["google_auth"] = True
        else:
            google_login_paid_for = False
            try:
                from ee.models.license import License
            except ImportError:
                pass
            else:
                license = License.objects.first_valid()
                if license is not None and "google_login" in license.available_features:
                    google_login_paid_for = True
            if google_login_paid_for:
                context["google_auth"] = True
            else:
                print_warning(["You have Google login set up, but not the required premium PostHog plan!"])

    if os.environ.get("SENTRY_DSN"):
        context["sentry_dsn"] = os.environ["SENTRY_DSN"]

    if settings.DEBUG and not settings.TEST:
        context["debug"] = True
        context["git_rev"] = get_git_commit()
        context["git_branch"] = get_git_branch()

    if settings.SELF_CAPTURE:
        if team:
            context["js_posthog_api_key"] = f"'{team.api_token}'"
            context["js_posthog_host"] = "window.location.origin"
    else:
        context["js_posthog_api_key"] = "'sTMFPsFhdP1Ssg'"
        context["js_posthog_host"] = "'https://app.posthog.com'"

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


def append_data(dates_filled: List, interval=None, math="sum") -> Dict[str, Any]:
    append: Dict[str, Any] = {}
    append["data"] = []
    append["labels"] = []
    append["days"] = []

    labels_format = "%a. {day} %B"
    days_format = "%Y-%m-%d"

    if interval == "hour" or interval == "minute":
        labels_format += ", %H:%M"
        days_format += " %H:%M:%S"

    for item in dates_filled:
        date = item[0]
        value = item[1]
        append["days"].append(date.strftime(days_format))
        append["labels"].append(date.strftime(labels_format.format(day=date.day)))
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
        ip = request.META.get("REMOTE_ADDR")  # Real IP address of client Machine
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


def generate_cache_key(stringified: str) -> str:
    return "cache_" + hashlib.md5(stringified.encode("utf-8")).hexdigest()


def get_celery_heartbeat() -> Union[str, int]:
    last_heartbeat = get_client().get("POSTHOG_HEARTBEAT")
    worker_heartbeat = int(time.time()) - int(last_heartbeat) if last_heartbeat else -1

    if 0 <= worker_heartbeat < 300:
        return worker_heartbeat
    return "offline"


def base64_to_json(data) -> Dict:
    return json.loads(
        base64.b64decode(data.replace(" ", "+") + "===")
        .decode("utf8", "surrogatepass")
        .encode("utf-16", "surrogatepass")
    )


# Used by non-DRF endpoins from capture.py and decide.py (/decide, /batch, /capture, etc)
def load_data_from_request(request):
    data_res: Dict[str, Any] = {"data": {}, "body": None}
    if request.method == "POST":
        if request.content_type == "application/json":
            data = request.body
            try:
                data_res["body"] = {**json.loads(request.body)}
            except:
                pass
        elif request.content_type == "text/plain":
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

    if compression == "gzip" or compression == "gzip-js":
        data = gzip.decompress(data)

    if compression == "lz64":
        if isinstance(data, str):
            data = lzstring.LZString().decompressFromBase64(data.replace(" ", "+"))
        else:
            data = lzstring.LZString().decompressFromBase64(data.decode().replace(" ", "+"))
        data = data.encode("utf-16", "surrogatepass").decode("utf-16")

    #  Is it plain json?
    try:
        # parse_constant gets called in case of NaN, Infinity etc
        # default behaviour is to put those into the DB directly
        # but we just want it to return None
        data = json.loads(data, parse_constant=lambda x: None)
    except json.JSONDecodeError:
        # if not, it's probably base64 encoded from other libraries
        data = base64_to_json(data)
    data_res["data"] = data
    # FIXME: data can also be an array, function assumes it's either None or a dictionary.
    return data_res


class SingletonDecorator:
    def __init__(self, klass):
        self.klass = klass
        self.instance = None

    def __call__(self, *args, **kwds):
        if self.instance == None:
            self.instance = self.klass(*args, **kwds)
        return self.instance


def get_machine_id() -> str:
    """A MAC address-dependent ID. Useful for PostHog instance analytics."""
    # MAC addresses are 6 bits long, so overflow shouldn't happen
    # hashing here as we don't care about the actual address, just it being rather consistent
    return hashlib.md5(uuid.getnode().to_bytes(6, "little")).hexdigest()


def get_table_size(table_name):
    from django.db import connection

    query = (
        f'SELECT pg_size_pretty(pg_total_relation_size(relid)) AS "size" '
        f"FROM pg_catalog.pg_statio_user_tables "
        f"WHERE relname = '{table_name}'"
    )
    cursor = connection.cursor()
    cursor.execute(query)
    return dict_from_cursor_fetchall(cursor)


def get_table_approx_count(table_name):
    from django.db import connection

    query = f"SELECT reltuples::BIGINT as \"approx_count\" FROM pg_class WHERE relname = '{table_name}'"
    cursor = connection.cursor()
    cursor.execute(query)
    return dict_from_cursor_fetchall(cursor)


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
        return ping and parser.isoparse(ping) > timezone.now() - relativedelta(seconds=30)
    except BaseException:
        return False


def get_redis_info() -> Mapping[str, Any]:
    return get_client().info()


def get_redis_queue_depth() -> int:
    return get_client().llen("celery")


def queryset_to_named_query(qs: QuerySet, prepend: str = "") -> Tuple[str, dict]:
    raw, params = qs.query.sql_with_params()
    arg_count = 0
    counter = count(arg_count)
    new_string = re.sub(r"%s", lambda _: f"%({prepend}_arg_{str(next(counter))})s", raw)
    named_params = {}
    for idx, param in enumerate(params):
        named_params.update({f"{prepend}_arg_{idx}": param})
    return new_string, named_params


def flatten(l: Union[List, Tuple]) -> Generator:
    for el in l:
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
    if frequency == "week":
        start_date += datetime.timedelta(days=6 - start_date.weekday())
    if frequency != "month":
        while start_date <= end_date:
            time_range.append(start_date)
            start_date += delta
    else:
        if start_date.day != 1:
            start_date = (start_date.replace(day=1) + delta).replace(day=1)
        while start_date <= end_date:
            time_range.append(start_date)
            start_date = (start_date.replace(day=1) + delta).replace(day=1)
    return time_range
