from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.conf import settings
from posthog.models import Event

import urllib.parse
import secrets
import json

def user(request):
    if not request.user.is_authenticated:
        return HttpResponse('Unauthorized', status=401)

    team = request.user.team_set.get()

    if request.method == 'PATCH':
        data = json.loads(request.body)
        team.app_urls = data['team'].get('app_urls', team.app_urls)
        team.opt_out_capture = data['team'].get('opt_out_capture', team.opt_out_capture)
        team.save()

    return JsonResponse({
        'id': request.user.pk,
        'distinct_id': request.user.distinct_id,
        'name': request.user.first_name,
        'email': request.user.email,
        'has_events': Event.objects.filter(team=team).exists(),
        'team': {
            'app_urls': team.app_urls,
            'api_token': team.api_token,
            'signup_token': team.signup_token,
            'opt_out_capture': team.opt_out_capture
        },
        'posthog_version': settings.VERSION
    })

def redirect_to_site(request):
    if not request.user.is_authenticated:
        return HttpResponse('Unauthorized', status=401)

    team = request.user.team_set.get()
    app_url = request.GET.get('appUrl') or (team.app_urls and team.app_urls[0])

    if not app_url:
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

    return redirect("{}#state={}".format(app_url, state))
