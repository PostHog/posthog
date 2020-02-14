from rest_framework import viewsets
from rest_framework.response import Response
from posthog.models import Event, PersonDistinctId, Team
from django.db.models import Subquery, OuterRef, Count, QuerySet
from typing import List, Optional
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta


# At the moment, paths don't support users changing distinct_ids midway through.
# See: https://github.com/PostHog/posthog/issues/185
class PathsViewSet(viewsets.ViewSet):
    def _url_subquery(self, event):
        return Event.objects.filter(pk=OuterRef(event)).values('properties__$current_url')[:1]

    def _add_event_and_url_at_position(self, aggregate: QuerySet, team: Team, index: int, date_from, urls: Optional[List[str]]=None) -> QuerySet:
        event_key = 'event_{}'.format(index)
        # adds event_1, url_1, event_2, url_2 etc for each Person
        return aggregate.annotate(**{
            event_key: Subquery(
                Event.objects.filter(
                    team=team,
                    timestamp__gte=date_from, 
                    pk__gt=OuterRef('event_{}'.format(index - 1)) if index > 1 else 0,
                    event='$pageview',
                    distinct_id=OuterRef('distinct_id'),
                    **{'properties__$current_url__isnull': False}
                )\
                .exclude(**({'properties__$current_url': OuterRef('url_{}'.format(index -1))} if index > 1 else {}))\
                .order_by('id').values('pk')[:1]
            ),
            'url_{}'.format(index): Subquery(self._url_subquery(event_key))
        })

    def list(self, request):
        team = request.user.team_set.get()
        resp = []
        aggregate = PersonDistinctId.objects.all()
        date_from = now() - relativedelta(days=7)
        aggregate = self._add_event_and_url_at_position(aggregate, team, 1, date_from)
        urls = False

        for index in range(1, 4):
            aggregate = self._add_event_and_url_at_position(aggregate, team, index+1, date_from)
            first_url_key = 'url_{}'.format(index)
            second_url_key = 'url_{}'.format(index + 1)
            rows = aggregate\
                .filter(
                    **({'{}__in'.format(first_url_key): urls} if urls else {}),
                    **{'{}__isnull'.format(second_url_key): False}
                )\
                .values(
                    first_url_key,
                    second_url_key
                )\
                .annotate(count=Count('pk'))\
                .order_by('-count')[0: 6]

            urls = []
            for row in rows:
                resp.append({
                    'source': '{}_{}'.format(index, row[first_url_key]),
                    'target': '{}_{}'.format(index + 1, row[second_url_key]),
                    'value': row['count']
                })
                urls.append(row[second_url_key])

        resp = sorted(resp, key=lambda x: x['value'], reverse=True)
        return Response(resp)