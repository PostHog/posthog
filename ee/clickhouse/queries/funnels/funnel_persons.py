import json
from typing import cast

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person


class ClickhouseFunnelPersons(ClickhouseFunnel):
    def get_query(self):
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            actor_column=self._filter.actor_column,
            offset=self._filter.offset,
            steps_per_person_query=self.get_step_counts_query(),
            persons_steps=self._get_funnel_person_step_condition(),
            timestamp="",
        )

    def _format_results(self, results):
        print(results)
        if self._filter.actor_column == "group_id":
            groups = (
                {
                    "id": row[0],
                    "type_id": row[1],
                    "created_at": row[2],
                    "team_id": row[3],
                    "properties": json.loads(row[4]),
                }
                for row in sync_execute(
                    """
                    SELECT id, type_id, created_at, team_id, properties FROM groups
                    WHERE team_id = %(team_id)s AND type_id = %(type_id)s AND has(%(group_ids)s, id)""",
                    {
                        "team_id": self._team.pk,
                        "type_id": self._filter.unique_group_type_id,
                        "group_ids": [val[0] for val in results],
                    },
                )
            )
            from ee.clickhouse.views.groups import GroupSerializer

            return GroupSerializer(groups, many=True).data, len(results) > cast(int, self._filter.limit) - 1
        else:
            people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

            from posthog.api.person import PersonSerializer

            return PersonSerializer(people, many=True).data, len(results) > cast(int, self._filter.limit) - 1
