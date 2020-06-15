from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from typing import Optional
from posthog.utils import cors_response
from urllib.parse import urlparse
import secrets


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

