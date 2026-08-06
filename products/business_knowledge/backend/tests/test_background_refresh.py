import datetime

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.scoping import team_scope

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.models import (
    KnowledgeDocument,
    KnowledgeSource,
    RefreshInterval,
    SourceStatus,
    SourceType,
)
from products.business_knowledge.backend.temporal.coordinator import RefreshSourceInputs, _host_serialized_batches


class TestDueRefreshSelection(BaseTest):
    def _url_source(self, *, interval: str, last_refresh_minutes_ago: int | None, status: str) -> KnowledgeSource:
        last_refresh_at = (
            timezone.now() - datetime.timedelta(minutes=last_refresh_minutes_ago)
            if last_refresh_minutes_ago is not None
            else None
        )
        with team_scope(self.team.id, canonical=True):
            return KnowledgeSource.objects.create(
                team=self.team,
                name="src",
                source_type=SourceType.URL,
                status=status,
                source_url="https://example.com",
                refresh_interval=interval,
                last_refresh_at=last_refresh_at,
            )

    def test_selects_only_due_non_manual_url_sources(self) -> None:
        due_overdue = self._url_source(
            interval=RefreshInterval.HOURLY, last_refresh_minutes_ago=120, status=SourceStatus.READY
        )
        self._url_source(interval=RefreshInterval.HOURLY, last_refresh_minutes_ago=10, status=SourceStatus.READY)
        self._url_source(interval=RefreshInterval.MANUAL, last_refresh_minutes_ago=None, status=SourceStatus.READY)
        due_never = self._url_source(
            interval=RefreshInterval.DAILY, last_refresh_minutes_ago=None, status=SourceStatus.READY
        )
        self._url_source(interval=RefreshInterval.HOURLY, last_refresh_minutes_ago=120, status=SourceStatus.PROCESSING)
        with team_scope(self.team.id, canonical=True):
            KnowledgeSource.objects.create(
                team=self.team,
                name="text",
                source_type=SourceType.TEXT,
                status=SourceStatus.READY,
                refresh_interval=RefreshInterval.HOURLY,
            )

        due = {source_id for _team_id, source_id, _host in logic.list_due_refresh_sources()}
        assert due == {due_overdue.id, due_never.id}

    def test_due_sources_carry_host(self) -> None:
        src = self._url_source(interval=RefreshInterval.HOURLY, last_refresh_minutes_ago=120, status=SourceStatus.READY)
        due = logic.list_due_refresh_sources()
        hosts = {source_id: host for _team_id, source_id, host in due}
        assert hosts[src.id] == "example.com"

    def test_respects_limit(self) -> None:
        for _ in range(3):
            self._url_source(interval=RefreshInterval.HOURLY, last_refresh_minutes_ago=120, status=SourceStatus.READY)
        assert len(logic.list_due_refresh_sources(limit=2)) == 2


class TestHostSerializedBatches(BaseTest):
    def test_same_host_never_shares_a_batch(self) -> None:
        # 3 sources on host A, 1 on host B, generous concurrency.
        due = [
            (1, "a1", "a.com"),
            (1, "a2", "a.com"),
            (1, "a3", "a.com"),
            (1, "b1", "b.com"),
        ]
        batches = _host_serialized_batches(due, max_concurrent=25)

        # Every a.com source lands in a distinct batch (serialized per host).
        for batch in batches:
            hosts_in_batch = [self._host_of(inp.source_id) for inp in batch]
            assert len(hosts_in_batch) == len(set(hosts_in_batch))
        # All sources are eventually scheduled exactly once.
        scheduled = [inp.source_id for batch in batches for inp in batch]
        assert sorted(scheduled) == ["a1", "a2", "a3", "b1"]

    def test_respects_max_concurrent(self) -> None:
        due = [(1, f"s{i}", f"h{i}.com") for i in range(10)]
        batches = _host_serialized_batches(due, max_concurrent=4)
        assert all(len(batch) <= 4 for batch in batches)
        assert sum(len(batch) for batch in batches) == 10

    @staticmethod
    def _host_of(source_id: str) -> str:
        # source ids are named after their host's first letter in the fixture.
        return source_id[0]

    def test_inputs_shape(self) -> None:
        batches = _host_serialized_batches([(7, "x", "x.com")], max_concurrent=25)
        assert batches == [[RefreshSourceInputs(team_id=7, source_id="x")]]


class TestTombstoneSweep(BaseTest):
    def _doc(self, *, source: KnowledgeSource, tombstoned_days_ago: int | None) -> KnowledgeDocument:
        tombstoned_at = (
            timezone.now() - datetime.timedelta(days=tombstoned_days_ago) if tombstoned_days_ago is not None else None
        )
        with team_scope(self.team.id, canonical=True):
            return KnowledgeDocument.objects.create(
                team=self.team,
                source=source,
                stable_id=f"https://example.com/{tombstoned_days_ago}",
                content="body",
                tombstoned_at=tombstoned_at,
            )

    def test_deletes_only_docs_past_grace_period(self) -> None:
        with team_scope(self.team.id, canonical=True):
            source = KnowledgeSource.objects.create(
                team=self.team, name="s", source_type=SourceType.URL, status=SourceStatus.READY
            )
        old = self._doc(source=source, tombstoned_days_ago=8)
        recent = self._doc(source=source, tombstoned_days_ago=1)
        live = self._doc(source=source, tombstoned_days_ago=None)

        deleted = logic.sweep_tombstoned_documents()

        assert deleted == 1
        with team_scope(self.team.id, canonical=True):
            remaining = set(KnowledgeDocument.objects.values_list("id", flat=True))
        assert old.id not in remaining
        assert {recent.id, live.id} <= remaining
