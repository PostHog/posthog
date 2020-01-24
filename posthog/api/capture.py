from posthog.models import Event, Team, Person
from django.http import HttpResponse, JsonResponse
import json
import base64
from django.views.decorators.csrf import csrf_exempt
from urllib.parse import urlparse


def get_ip_address(request):
    """ use requestobject to fetch client machine's IP Address """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')    ### Real IP address of client Machine
    return ip   

def cors_response(request, response):
    url = urlparse(request.META['HTTP_REFERER'])
    response["Access-Control-Allow-Origin"] = "%s://%s" % (url.scheme, url.netloc)
    response["Access-Control-Allow-Credentials"] = 'true'
    response["Access-Control-Allow-Methods"] = 'GET, POST, OPTIONS'
    response["Access-Control-Allow-Headers"] = 'X-Requested-With'
    return response

@csrf_exempt
def get_event(request):
    data = request.GET.get('data')
    if not data:
        return HttpResponse("1")
    
    data = json.loads(base64.b64decode(data))
    print(data)
    team = Team.objects.get(api_token=data['properties']['token'])

    Event.objects.create(
        event=data['event'],
        properties=data['properties'],
        ip=get_ip_address(request),
        team=team
    )

    if not Person.objects.filter(team=team, distinct_ids__contains=data['properties']['distinct_id']).exists():
        Person.objects.create(team=team, distinct_ids=[data['properties']['distinct_id']])
    return cors_response(request, HttpResponse("1"))


@csrf_exempt
def get_decide(request):
    return cors_response(request, JsonResponse({"config": {"enable_collect_everything": True}}))

@csrf_exempt
def get_engage(request):
    data = request.GET.get('data')
    if not data:
        return HttpResponse("1")
    
    data = json.loads(base64.b64decode(data))
    print(data)
    team = Team.objects.get(api_token=data['$token'])

    person = Person.objects.get(team=team, distinct_ids__contains=data['$distinct_id'])
    if data.get('$set'):
        person.properties = data['$set']
        person.save()
 
    return cors_response(request, HttpResponse("1"))