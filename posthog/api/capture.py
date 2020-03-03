from posthog.models import Event, Team, Person, Element, PersonDistinctId
from django.http import HttpResponse, JsonResponse
from django.db import IntegrityError
from django.views.decorators.csrf import csrf_exempt
import json
import base64
from urllib.parse import urlparse
from typing import Dict, Union, Optional, List


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

def _load_data(request) -> Union[Dict, None]:
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
    return data

def _alias(distinct_id: str, new_distinct_id: str, team: Team):
    person = Person.objects.get(team=team, persondistinctid__distinct_id=distinct_id)
    try:
        person.add_distinct_id(new_distinct_id)
    except IntegrityError:
        # IntegrityError means a person with new_distinct_id already exists
        # That can either mean `person` already has that distinct_id, in which case we do nothing
        # OR it means there is _another_ Person with that distinct _id, in which case we want to remove that person
        # and add that distinct ID to `person`
        previous_person = Person.objects.filter(persondistinctid__distinct_id=new_distinct_id).exclude(pk=person.id)
        if previous_person.exists():
            person.properties.update(previous_person.first().properties) # type: ignore
            previous_person.delete()
            person.add_distinct_id(new_distinct_id)
            person.save()

def _capture(request, team: Team, event: str, distinct_id: str, properties: Dict, timestamp: Optional[str]=None) -> None:
    elements = properties.get('$elements')
    elements_list = None
    if elements:
        del properties['$elements']
        elements_list = [
            Element(
                text=el.get('$el_text'),
                tag_name=el['tag_name'],
                href=el.get('attr__href'),
                attr_class=el['attr__class'].split(' ') if el.get('attr__class') else None,
                attr_id=el.get('attr__id'),
                nth_child=el.get('nth_child'),
                nth_of_type=el.get('nth_of_type'),
                attributes={key: value for key, value in el.items() if key.startswith('attr__')},
                order=index
            ) for index, el in enumerate(elements)
        ]
    db_event = Event.objects.create(
        event=event,
        distinct_id=distinct_id,
        properties=properties,
        ip=get_ip_address(request),
        team=team,
        **({'timestamp': timestamp} if timestamp else {}),
        **({'elements': elements_list} if elements_list else {})
    )

    # try to create a new person
    try:
        Person.objects.create(team=team, distinct_ids=[str(distinct_id)], is_user=request.user if not request.user.is_anonymous else None)
    except IntegrityError: 
        pass # person already exists, which is fine

def _update_person_properties(team: Team, distinct_id: str, properties: Dict):
    try:
        person = Person.objects.get(team=team, persondistinctid__distinct_id=str(distinct_id))
    except Person.DoesNotExist:
        person = Person.objects.create(team=team, distinct_ids=[str(distinct_id)])
    person.properties.update(properties)
    person.save()

def process_event(request, data: dict, team: Team) -> None:
    try:
        distinct_id = str(data['properties']['distinct_id'])
    except KeyError:
        try:
            distinct_id = str(data['$distinct_id'])
        except KeyError:
            distinct_id = str(data['distinct_id'])

    if data['event'] == '$create_alias':
        _alias(distinct_id=distinct_id, new_distinct_id=data['properties']['alias'], team=team)

    if data['event'] == '$identify' and data.get('properties') and data['properties'].get('$anon_distinct_id'):
        _alias(distinct_id=data['properties']['$anon_distinct_id'], new_distinct_id=distinct_id, team=team)

    if data['event'] == '$identify' and data.get('$set'):
        _update_person_properties(team=team, distinct_id=distinct_id, properties=data['$set'])

    _capture(request=request, team=team, event=data['event'], distinct_id=distinct_id, properties=data.get('properties', data.get('$set', {})), timestamp=data.get('timestamp'))

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
    data = _load_data(request)
    if not data:
        return cors_response(request, HttpResponse("1"))
    token = _get_token(data, request)
    if not token:
        return cors_response(request, JsonResponse({'code': 'validation', 'message': "No api_key set. You can find your API key in the /setup page in posthog"}, status=400))

    if not isinstance(data, list) and data.get('batch'): # posthog-python and posthog-ruby
        data = data['batch']

    if 'engage' in request.path_info: # JS identify call
        data['event'] = '$identify' # make sure it has an event name

    try:
        team = Team.objects.get(api_token=token)
    except Team.DoesNotExist:
        return cors_response(request, JsonResponse({'code': 'validation', 'message': "API key is incorrect. You can find your API key in the /setup page in PostHog."}, status=400))

    if isinstance(data, list):
        for i in data:
            try:
                process_event(request=request, data=i, team=team)
            except KeyError:
                return cors_response(request, JsonResponse({'code': 'validation', 'message': "You need to set a distinct_id.", "item": data}, status=400))
    else:
        process_event(request=request, data=data, team=team)

    return cors_response(request, JsonResponse({'status': 1}))

@csrf_exempt
def get_decide(request):
    return cors_response(request, JsonResponse({"config": {"enable_collect_everything": True}}))