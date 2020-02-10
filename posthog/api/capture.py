from posthog.models import Event, Team, Person, Element, PersonDistinctId
from django.http import HttpResponse, JsonResponse
from django.db import IntegrityError
from django.views.decorators.csrf import csrf_exempt
import json
import base64
from urllib.parse import urlparse
from typing import Dict, Union, Optional


def get_ip_address(request):
    """ use requestobject to fetch client machine's IP Address """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')    ### Real IP address of client Machine
    return ip   

def cors_response(request, response):
    if not request.META.get('HTTP_REFERER'):
        return response
    url = urlparse(request.META['HTTP_REFERER'])
    response["Access-Control-Allow-Origin"] = "%s://%s" % (url.scheme, url.netloc)
    response["Access-Control-Allow-Credentials"] = 'true'
    response["Access-Control-Allow-Methods"] = 'GET, POST, OPTIONS'
    response["Access-Control-Allow-Headers"] = 'X-Requested-With'
    return response

def _load_data(request) -> Union[Dict, None]:
    if request.method == 'POST':
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
        data = json.loads(base64.b64decode(data).decode('utf8', 'surrogatepass').encode('utf-16', 'surrogatepass'))
    return data

def _alias(distinct_id: str, new_distinct_id: str, request):
    person = Person.objects.get(persondistinctid__distinct_id=distinct_id)
    person.add_distinct_id(new_distinct_id)
    return cors_response(request, JsonResponse({'status': 1}))

def _capture(request, token: str, event: str, distinct_id: str, properties: Dict, timestamp: Optional[str]=None) -> None:
    team = Team.objects.get(api_token=token)

    elements = properties.get('$elements')
    if elements:
        del properties['$elements']
    db_event = Event.objects.create(
        event=event,
        distinct_id=distinct_id,
        properties=properties,
        ip=get_ip_address(request),
        team=team,
        **({'timestamp': timestamp} if timestamp else {})
    )
    if elements: 
        Element.objects.bulk_create([
            Element(
                text=el.get('$el_text'),
                tag_name=el['tag_name'],
                href=el.get('attr__href'),
                attr_class=el['attr__class'].split(' ') if el.get('attr__class') else None,
                attr_id=el.get('attr__id'),
                nth_child=el.get('nth_child'),
                nth_of_type=el.get('nth_of_type'),
                attributes={key: value for key, value in el.items() if key.startswith('attr__')},
                event=db_event,
                order=index
            ) for index, el in enumerate(elements)
        ])

    # try to create a new person
    try:
        Person.objects.create(team=team, distinct_ids=[str(distinct_id)], is_user=request.user if not request.user.is_anonymous else None)
    except IntegrityError: 
        pass # person already exists, which is fine

    return cors_response(request, JsonResponse({'status': 1}))

def _engage(token: str, distinct_id: str, properties: Dict, request):
    team = Team.objects.get(api_token=token)

    try:
        person = Person.objects.get(team=team, persondistinctid__distinct_id=str(distinct_id))
    except Person.DoesNotExist:
        person = Person.objects.create(team=team, distinct_ids=[str(distinct_id)])
    person.properties.update(properties)
    person.save()
    return cors_response(request, JsonResponse({'status': 1}))

@csrf_exempt
def get_event(request):
    data = _load_data(request)
    if not data:
        return cors_response(request, HttpResponse("1"))

    if request.POST.get('api_key'):
        token = request.POST['api_key']
    else:
        token = data['properties'].pop('token')

    distinct_id = str(data['properties']['distinct_id'])

    if data['event'] == '$create_alias':
        return _alias(distinct_id=distinct_id, new_distinct_id=data['properties']['alias'], request=request)

    return _capture(request=request, token=token, event=data['event'], distinct_id=distinct_id, properties=data['properties'])

    return cors_response(request, JsonResponse({'status': 1}))


@csrf_exempt
def get_decide(request):
    return cors_response(request, JsonResponse({"config": {"enable_collect_everything": True}}))

@csrf_exempt
def get_engage(request):
    data = _load_data(request)
    if not data:
        return cors_response(request, HttpResponse("1"))
    
    if request.POST.get('api_key'):
        token = request.POST['api_key']
    else:
        token = data.pop('$token')

    if data.get('$set'):
        return _engage(token=token, distinct_id=data['$distinct_id'], properties=data['$set'], request=request)

    return cors_response(request, JsonResponse({'status': 1}))

@csrf_exempt
def batch(request):
    batch = json.loads(request.body)
    for data in batch['batch']:
        if data['type'] == 'alias':
            return _alias(
                distinct_id=data['properties']['distinct_id'],
                new_distinct_id=data['properties']['alias'],
                request=request
            )
        elif data['type'] == 'capture':
            return _capture(
                request=request,
                token=data['api_key'],
                event=data['event'],
                distinct_id=data['distinct_id'],
                properties=data['properties'],
                timestamp=data['timestamp']
            )
        elif data['type'] == 'identify':
            return _engage(
                token=data['api_key'],
                distinct_id=data['distinct_id'],
                properties=data['$set'],
                request=request
            )
    return cors_response(request, JsonResponse({'status': 1}))