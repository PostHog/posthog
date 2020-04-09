from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from django.db.models import Q
from typing import Dict
from django.template.loader import get_template
from django.http import HttpResponse, JsonResponse

import datetime
import re
import os

def relative_date_parse(input: str) -> datetime.date:
    try:
        return datetime.datetime.strptime(input, '%Y-%m-%d').date()
    except ValueError:
        pass

    regex = r"\-?(?P<number>[0-9]+)?(?P<type>[a-z])(?P<position>Start|End)?"
    match = re.search(regex, input)
    date = now()
    if not match:
        return date
    if match.group('type') == 'd':
        if match.group('number'):
            date = date - relativedelta(days=int(match.group('number')))
    elif match.group('type') == 'm':
        if match.group('number'):
            date = date - relativedelta(months=int(match.group('number')))
        if match.group('position') == 'Start':
            date = date - relativedelta(day=1)
        if match.group('position') == 'End':
            date = date - relativedelta(day=31)
    elif match.group('type') == 'y':
        if match.group('number'):
            date = date - relativedelta(years=int(match.group('number')))
        if match.group('position') == 'Start':
            date = date - relativedelta(month=1, day=1)
        if match.group('position') == 'End':
            date = date - relativedelta(month=12, day=31)
    return date.date()

def request_to_date_query(request) -> Dict[str, datetime.date]:
    if request.GET.get('date_from'):
        date_from = relative_date_parse(request.GET['date_from'])
        if request.GET['date_from'] == 'all':
            date_from = None # type: ignore
    else:
        date_from = datetime.date.today() - relativedelta(days=7)

    date_to = None
    if request.GET.get('date_to'):
        date_to = relative_date_parse(request.GET['date_to'])

    resp = {}
    if date_from:
        resp['timestamp__gte'] = date_from
    if date_to:
        resp['timestamp__lte'] = date_to + relativedelta(days=1)
    return resp

def properties_to_Q(properties: Dict[str, str]) -> Q:
    filters = Q()

    for key, value in properties.items():
        if key.endswith('__is_not'):
            key = key.replace('__is_not', '')
            filters |= Q(~Q(**{'properties__{}'.format(key): value}) | ~Q(properties__has_key=key))
        elif key.endswith('__not_icontains'):
            key = key.replace('__not_icontains', '')
            filters |= Q(~Q(**{'properties__{}__icontains'.format(key): value}) | ~Q(properties__has_key=key))
        else:
            filters |= Q(**{'properties__{}'.format(key): value})
    return filters

def render_template(template_name: str, request, context=None) -> HttpResponse:
    from posthog.models import Team
    if context is None:
        context = {}
    template = get_template(template_name)
    try:
        context.update({
            'opt_out_capture': request.user.team_set.get().opt_out_capture
        })
    except (Team.DoesNotExist, AttributeError):
        team = Team.objects.all()
        # if there's one team on the instance, and they've set opt_out
        # we'll opt out anonymous users too
        if team.count() == 1:
            context.update({
                'opt_out_capture': team.first().opt_out_capture, # type: ignore
            })

    if os.environ.get('SENTRY_DSN'):
        context.update({
            'sentry_dsn': os.environ['SENTRY_DSN']
        })

    attach_social_auth(context)
    html = template.render(context, request=request)
    return HttpResponse(html)

def attach_social_auth(context):
    if os.environ.get('SOCIAL_AUTH_GITHUB_KEY') and os.environ.get('SOCIAL_AUTH_GITHUB_SECRET'):
        context.update({
            'github_auth': True
        })
    if os.environ.get('SOCIAL_AUTH_GITLAB_KEY') and os.environ.get('SOCIAL_AUTH_GITLAB_SECRET'):
        context.update({
            'gitlab_auth': True
        })
    