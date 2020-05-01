from rest_framework import viewsets
from rest_framework.response import Response
from posthog.models import Event, PersonDistinctId, Team
from posthog.utils import request_to_date_query
from django.db.models import Subquery, OuterRef, Count, QuerySet
from typing import List, Optional, Dict
from django.utils.timezone import now
import datetime


# At the moment, paths don't support users changing distinct_ids midway through.
# See: https://github.com/PostHog/posthog/issues/185
class PathsViewSet(viewsets.ViewSet):
    def _event_subquery(self, event: str, key: str):
        return Event.objects.filter(pk=OuterRef(event)).values(key)[:1]

    # FIXME: Timestamp is timezone aware timestamp, date range uses naive date.
    # To avoid unexpected results should convert date range to timestamps with timezone.
    def _add_event_and_url_at_position(self, aggregate: QuerySet, team: Team, index: int, date_query: Dict[str, datetime.date], urls: Optional[List[str]]=None) -> QuerySet:
        event_key = 'event_{}'.format(index)

        # adds event_1, url_1, event_2, url_2 etc for each Person
        return aggregate.annotate(**{
            event_key: Subquery(
                Event.objects.filter(
                    team=team,
                    event='$pageview',
                    distinct_id=OuterRef('distinct_id'),
                    **date_query,
                    **{'properties__$current_url__isnull': False},
                    **({'timestamp__gt': OuterRef('timestamp_{}'.format(index - 1))} if index > 1 else {})
                )\
                .exclude(**({'properties__$current_url': OuterRef('url_{}'.format(index -1))} if index > 1 else {}))\
                .order_by('id').values('pk')[:1]
            ),
            'timestamp_{}'.format(index): self._event_subquery(event_key, 'timestamp'),
            'url_{}'.format(index): self._event_subquery(event_key, 'properties__$current_url')
        })

    def list(self, request):
        team = request.user.team_set.get()
        resp = []
        date_query = request_to_date_query(request.GET)
        aggregate: QuerySet[PersonDistinctId] = PersonDistinctId.objects.filter(team=team)

        aggregate = self._add_event_and_url_at_position(aggregate, team, 1, date_query)
        urls: List[str] = []

        for index in range(1, 4):
            aggregate = self._add_event_and_url_at_position(aggregate, team, index+1, date_query)
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
