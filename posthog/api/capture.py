from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from posthog.models import Team
from typing import Dict, Union, Optional, List
from urllib.parse import urlparse
from posthog.tasks.process_event import process_event
import json
import base64
import datetime


def get_ip_address(request):
    """ use requestobject to fetch client machine's IP Address """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')    ### Real IP address of client Machine
    return ip   

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
        else:
            data = request.POST.get('data')
    else:
        data = request.GET.get('data')
    if not data:
        return None

    #  Is it plain json?
    try:
        data = json.loads(data)
    except json.JSONDecodeError:
        # if not, it's probably base64 encoded from other libraries
        data = json.loads(base64.b64decode(data + "===").decode('utf8', 'surrogatepass').encode('utf-16', 'surrogatepass'))
    # FIXME: data can also be an array, function assumes it's either None or a dictionary.
    return data


def _get_token(data, request) -> Union[str, bool]:
    if request.POST.get('api_key'):
        return request.POST['api_key']
    if isinstance(data, list) and len(data) > 0:
        return data[0]['properties']['token'] # Mixpanel Swift SDK
    if data.get('api_key'):
        return data['api_key'] # server-side libraries like posthog-python and posthog-ruby
    if data.get('$token'):
        return data['$token'] # JS identify call
    if data.get('properties') and data['properties'].get('token'):
        return data['properties']['token'] # JS capture call
    return False

@csrf_exempt
def get_event(request):
    now = timezone.now()
    data = _load_data(request)
    if not data:
        return cors_response(request, HttpResponse("1"))
    token = _get_token(data, request)
    if not token:
        return cors_response(request, JsonResponse({'code': 'validation', 'message': "No api_key set. You can find your API key in the /setup page in posthog"}, status=400))

    try:
        team = Team.objects.only('pk').get(api_token=token)
    except Team.DoesNotExist:
        return cors_response(request, JsonResponse({'code': 'validation', 'message': "API key is incorrect. You can find your API key in the /setup page in PostHog."}, status=400))

    if isinstance(data, dict):
        if data.get('batch'): # posthog-python and posthog-ruby
            data = data['batch']
            assert data is not None
        elif 'engage' in request.path_info: # JS identify call
            data['event'] = '$identify' # make sure it has an event name

    if isinstance(data, list):
        for i in data:
            try:
                process_event.delay(
                    ip=get_ip_address(request),
                    site_url=request.build_absolute_uri('/')[:-1],
                    data=i, team_id=team.pk, now=now)
            except KeyError:
                return cors_response(request, JsonResponse({'code': 'validation', 'message': "You need to set a distinct_id.", "item": data}, status=400))
    else:
        process_event.delay(
            ip=get_ip_address(request),
            site_url=request.build_absolute_uri('/')[:-1],
            data=data,
            team_id=team.pk,
            now=now)

    return cors_response(request, JsonResponse({'status': 1}))

@csrf_exempt
def get_decide(request):
    return cors_response(request, JsonResponse({"config": {"enable_collect_everything": True}}))