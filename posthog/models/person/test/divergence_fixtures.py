from typing import TYPE_CHECKING

from django.utils.timezone import now

from posthog.clickhouse.client import sync_execute
from posthog.models.person.sql import BULK_INSERT_PERSON_DISTINCT_ID2
from posthog.models.person.util import create_person as create_person_in_ch
from posthog.models.signals import mute_selected_signals
from posthog.test.persons import add_distinct_id, create_person

if TYPE_CHECKING:
    from posthog.models.team import Team


class DivergenceFixturesMixin:
    """Writes Postgres (personhog fake) and ClickHouse person state independently, so a test can build any
    disagreement between them. Needs ClickhouseTestMixin and BaseTest."""

    team: "Team"

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        # A background merge collapses the duplicate and older rows the tie and blanked shapes are made of.
        for table in ("person", "person_distinct_id2"):
            sync_execute(f"SYSTEM STOP MERGES {table}")
            self.addCleanup(sync_execute, f"SYSTEM START MERGES {table}")  # type: ignore[attr-defined]

    def _pg_person(self, *, version: int, distinct_ids: list[str] | None = None):
        with mute_selected_signals():
            person = create_person(team=self.team, version=version, properties={"email": "pg@example.com"})
            for distinct_id in distinct_ids or []:
                add_distinct_id(person=person, distinct_id=distinct_id, version=0)
        return person

    def _ch_person(
        self, person_uuid: str, version: int, properties: dict, *, deleted: bool = False, identified: bool = False
    ) -> None:
        create_person_in_ch(
            team_id=self.team.pk,
            uuid=person_uuid,
            version=version,
            is_identified=identified,
            is_deleted=deleted,
            properties=properties,
            timestamp=now(),
        )

    def _ch_mapping(self, distinct_id: str, person_uuid: str, version: int, *, team_id: int | None = None) -> None:
        sync_execute(
            BULK_INSERT_PERSON_DISTINCT_ID2,
            [
                {
                    "distinct_id": distinct_id,
                    "person_id": person_uuid,
                    "team_id": team_id or self.team.pk,
                    "is_deleted": 0,
                    "version": version,
                    "_timestamp": now().replace(tzinfo=None),
                    "_offset": 0,
                    "_partition": 0,
                }
            ],
            flush=False,
        )
