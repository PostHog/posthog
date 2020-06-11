from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from posthog.models import Team
from posthog.utils import get_ip_address
from typing import Dict, Union, Optional, List, Any
from urllib.parse import urlparse
from posthog.tasks.process_event import process_event
from datetime import datetime
from dateutil import parser
from sentry_sdk import push_scope
import re
import json
import secrets
import base64
import gzip

TEAM_ID_CACHE: Dict[str, int] = {}

def cors_response(request, response):
    if not request.META.get('HTTP_ORIGIN'):
        return response
    url = urlparse(request.META['HTTP_ORIGIN'])
    response["Access-Control-Allow-Origin"] = "%s://%s" % (url.scheme, url.netloc)
    response["Access-Control-Allow-Credentials"] = 'true'
    response["Access-Control-Allow-Methods"] = 'GET, POST, OPTIONS'
    response["Access-Control-Allow-Headers"] = 'X-Requested-With'
    return response

def _load_data(request) -> Optional[Union[Dict, List]]:
    if request.method == 'POST':
        if request.content_type == 'application/json':
            data = request.body

            if request.headers.get('content-encoding', '').lower() == 'gzip':
                data = gzip.decompress(data)
        else:
            data = request.POST.get('data')
    else:
        data = request.GET.get('data')
    if not data:
        return None

    # add the data in sentry's scope in case there's an exception
    with push_scope() as scope:
        scope.set_context("data", data)

    #  Is it plain json?
    try:
        data = json.loads(data)
    except json.JSONDecodeError:
        # if not, it's probably base64 encoded from other libraries
        data = json.loads(base64.b64decode(data.replace(' ', '+') + "===").decode('utf8', 'surrogatepass').encode('utf-16', 'surrogatepass'))
    # FIXME: data can also be an array, function assumes it's either None or a dictionary.
    return data


def _datetime_from_seconds_or_millis(timestamp: str) -> datetime:
    if len(timestamp) > 11:  # assuming milliseconds / update "11" to "12" if year > 5138 (set a reminder!)
        timestamp_number = float(timestamp) / 1000
    else:
        timestamp_number = int(timestamp)

    return datetime.fromtimestamp(timestamp_number, timezone.utc)


def _get_sent_at(data, request) -> Optional[datetime]:
    if request.GET.get('_'):  # posthog-js
        sent_at = request.GET['_']
    elif isinstance(data, dict) and data.get('sent_at'):  # posthog-android, posthog-ios
        sent_at = data['sent_at']
    elif request.POST.get('sent_at'):  # when urlencoded body and not JSON (in some test)
        sent_at = request.POST['sent_at']
    else:
        return None

    if re.match(r"^[0-9]+$", sent_at):
        return _datetime_from_seconds_or_millis(sent_at)

    return parser.isoparse(sent_at)


def _get_token(data, request) -> Optional[str]:
    if request.POST.get('api_key'):
        return request.POST['api_key']
    if isinstance(data, list) and len(data) > 0:
        return data[0]['properties']['token'] # Mixpanel Swift SDK
    if data.get('$token'):
        return data['$token'] # JS identify call
    if data.get('api_key'):
        return data['api_key'] # server-side libraries like posthog-python and posthog-ruby
    if data.get('properties') and data['properties'].get('token'):
        return data['properties']['token'] # JS capture call
    return None

def _get_distinct_id(data: Dict[str, Any]) -> str:
    try:
        return str(data['$distinct_id'])
    except KeyError:
        try:
            return str(data['properties']['distinct_id'])
        except KeyError:
            return str(data['distinct_id'])

@csrf_exempt
def get_event(request):
    now = timezone.now()
    data = _load_data(request)
    if not data:
        return cors_response(request, HttpResponse("1"))
    sent_at = _get_sent_at(data, request)
    token = _get_token(data, request)
    if not token:
        return cors_response(request, JsonResponse({'code': 'validation', 'message': "No api_key set. You can find your API key in the /setup page in posthog"}, status=400))

    team_id = TEAM_ID_CACHE.get(token)
    if not team_id:
        try:
            team_id = Team.objects.only('pk').get(api_token=token).pk
            if team_id:
                TEAM_ID_CACHE[token] = team_id
        except Team.DoesNotExist:
            return cors_response(request, JsonResponse({'code': 'validation', 'message': "API key is incorrect. You can find your API key in the /setup page in PostHog."}, status=400))

    if isinstance(data, dict):
        if data.get('batch'): # posthog-python and posthog-ruby
            data = data['batch']
            assert data is not None
        elif 'engage' in request.path_info: # JS identify call
            data['event'] = '$identify' # make sure it has an event name

    if isinstance(data, list):
        events = data
    else:
        events = [data]

    for event in events:
        try:
            distinct_id = _get_distinct_id(event)
        except KeyError:
            return cors_response(request, JsonResponse({'code': 'validation', 'message': "You need to set a distinct_id.", "item": event}, status=400))
        process_event.delay(
            distinct_id=distinct_id,
            ip=get_ip_address(request),
            site_url=request.build_absolute_uri('/')[:-1],
            data=event,
            team_id=team_id,
            now=now,
            sent_at=sent_at,
        )

    return cors_response(request, JsonResponse({'status': 1}))


def parse_domain(url: str) -> Optional[str]:
    return urlparse(url).hostname


@csrf_exempt
def get_decide(request):
    response = {
        'config': {'enable_collect_everything': True},
        'editorParams': {},
        'isAuthenticated': False
    }

    if request.user.is_authenticated:
        team = request.user.team_set.get()
        permitted_domains = ['127.0.0.1', 'localhost']

        for url in team.app_urls:
            hostname = parse_domain(url)
            if hostname:
                permitted_domains.append(hostname)

        if (parse_domain(request.headers.get('Origin')) in permitted_domains) or (parse_domain(request.headers.get('Referer')) in permitted_domains):
            response['isAuthenticated'] = True
            editor_params = {}
            if hasattr(settings, 'TOOLBAR_VERSION'):
                editor_params['toolbarVersion'] = settings.TOOLBAR_VERSION
            if settings.DEBUG:
                editor_params['jsURL'] = 'http://localhost:8234/'

            response['editorParams'] = editor_params

            if not request.user.temporary_token:
                request.user.temporary_token = secrets.token_urlsafe(32)
                request.user.save()
    return cors_response(request, JsonResponse(response))

