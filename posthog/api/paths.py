from rest_framework import viewsets
from rest_framework.response import Response
from posthog.models import Event, PersonDistinctId, Team, ElementGroup
from posthog.utils import request_to_date_query
from django.db.models import Subquery, OuterRef, Count, QuerySet
from typing import List, Optional, Dict
import datetime


# At the moment, paths don't support users changing distinct_ids midway through.
# See: https://github.com/PostHog/posthog/issues/185
class PathsViewSet(viewsets.ViewSet):
    def _event_subquery(self, event: str, key: str):
        return Event.objects.filter(pk=OuterRef(event)).values(key)[:1]

    # FIXME: Timestamp is timezone aware timestamp, date range uses naive date.
    # To avoid unexpected results should convert date range to timestamps with timezone.
    def _add_event_step(self, event:str, aggregate: QuerySet, team: Team, index: int, date_query: Dict[str, datetime.date],  path_type: str, urls: Optional[List[str]]=None) -> QuerySet:
        event_key = '{}_{}'.format(event, index)

        # adds event_1, url_1, event_2, url_2 etc for each Person
        return aggregate.annotate(**{
            event_key: Subquery(
                Event.objects.filter(
                    team=team,
                    **({"event":event} if event else {}),
                    distinct_id=OuterRef('distinct_id'),
                    **date_query,
                    **{'{}__isnull'.format(path_type): False},
                    **({'timestamp__gt': OuterRef('timestamp_{}'.format(index - 1))} if index > 1 else {})
                )\
                .exclude(**({'{}'.format(path_type): OuterRef('{}_{}'.format(path_type, index -1))} if index > 1 else {}))\
                .order_by('id').values('pk')[:1]
            ),
            'timestamp_{}'.format(index): self._event_subquery(event_key, 'timestamp'),
            '{}_{}'.format(path_type, index): self._event_subquery(event_key, '{}'.format(path_type))
        })

    def _determine_path_type(self, request):
        event = "$pageview"
        path_type = "properties__$current_url"

        # determine requested type
        requested_type = request.GET.get('type', None)
        if requested_type:
            if requested_type == "$screen":
                event = "$screen"
                path_type = "properties__$screen"
            elif requested_type == "$autocapture":
                event = "$autocapture"
                path_type = "elements_hash"
            elif requested_type == "custom_event":
                event = None
                path_type = "event"
        return event, path_type

    def list(self, request):
        team = request.user.team_set.get()
        resp = []
        date_query = request_to_date_query(request.GET)
        aggregate: QuerySet[PersonDistinctId] = PersonDistinctId.objects.filter(team=team)
        event, path_type = self._determine_path_type(request)

        aggregate = self._add_event_step(event, aggregate, team, 1, date_query, path_type)
        urls: List[str] = []
        for index in range(1, 4):
            aggregate = self._add_event_step(event, aggregate, team, index+1, date_query, path_type)
            first_url_key = '{}_{}'.format(path_type, index)
            second_url_key = '{}_{}'.format(path_type, index + 1)
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
                source_element = ElementGroup.objects.get(hash=row[first_url_key]).element_set.all().order_by('order')[:1] if event == "$autocapture" else QuerySet()
                target_element = ElementGroup.objects.get(hash=row[second_url_key]).element_set.all().order_by('order')[:1] if event == "$autocapture" else QuerySet()
                resp.append({
                    'sourceLabel': '<{}> {}'.format(source_element.values()[0]['tag_name'], "with text \"{}\"".format(source_element.values()[0]['text'])if source_element.values()[0]['text'] else "") if event == "$autocapture" else '{}_{}'.format(index, row[first_url_key]),
                    'targetLabel': '<{}> {}'.format(target_element.values()[0]['tag_name'], "with text \"{}\"".format(target_element.values()[0]['text'])if target_element.values()[0]['text'] else "") if event == "$autocapture" else '{}_{}'.format(index, row[second_url_key]),
                    'source': '{}_{}'.format(index, row[first_url_key]),
                    'target': '{}_{}'.format(index + 1, row[second_url_key]),
                    'value': row['count']
                })
                urls.append(row[second_url_key])
            
        resp = sorted(resp, key=lambda x: x['value'], reverse=True)
        return Response(resp)
