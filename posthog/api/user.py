from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect

import urllib.parse
import secrets
import json

def user(request):
    if not request.user.is_authenticated:
        return HttpResponse('Unauthorized', status=401)

    team = request.user.team_set.get()

    if request.method == 'PATCH':
        data = json.loads(request.body)
        team.app_url = data['team']['app_url']
        team.save()

    return JsonResponse({
        'id': request.user.pk,
        'distinct_id': request.user.distinct_id,
        'name': request.user.first_name,
        'email': request.user.email,
        'team': {
            'app_url': team.app_url,
            'api_token': team.api_token
        }
    })

def redirect_to_site(request):
    if not request.user.is_authenticated:
        return HttpResponse('Unauthorized', status=401)

    team = request.user.team_set.get()
    if not team.app_url:
        return HttpResponse(status=404)

    request.user.temporary_token = secrets.token_urlsafe(32)
    request.user.save()
    state = urllib.parse.quote(json.dumps({
        'action': 'mpeditor',
        'token': team.api_token,
        'temporaryToken': request.user.temporary_token,
        'actionId': request.GET.get('actionId'),
        'apiURL': request.build_absolute_uri('/')
    }))

    return redirect("{}#state={}".format(team.app_url, state))