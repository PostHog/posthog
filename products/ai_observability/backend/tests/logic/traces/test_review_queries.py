from decimal import Decimal

from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.logic.traces.review import (
    HumanReview,
    QueueAssignment,
    ReviewScore,
    TraceReviewState,
)
from products.ai_observability.backend.logic.traces.review_queries import (
    load_trace_review_state,
    load_trace_review_states,
)
from products.ai_observability.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.ai_observability.backend.models.score_definitions import ScoreDefinition
from products.ai_observability.backend.models.trace_reviews import TraceReview, TraceReviewScore

TRACE_ID = "trace-1"
NOTHING = TraceReviewState(review=None, queue=None)


class TestLoadTraceReviewState(BaseTest):
    def _score(self, review: TraceReview, *, name: str, kind: str, config: dict[str, object], **value: object) -> None:
        definition = ScoreDefinition.objects.create(team=self.team, name=name, kind=kind, created_by=self.user)
        version = definition.create_new_version(config=config, created_by=self.user)
        TraceReviewScore.objects.create(
            team=self.team,
            review=review,
            definition=definition,
            definition_version=version.id,
            definition_version_number=version.version,
            definition_config=version.config,
            created_by=self.user,
            **value,
        )

    def _review(self, *, team: Team | None = None, deleted: bool = False) -> TraceReview:
        return TraceReview.objects.create(
            team=team or self.team,
            trace_id=TRACE_ID,
            comment="Looks right",
            reviewed_by=self.user,
            created_by=self.user,
            deleted=deleted,
        )

    def _queue_item(self, *, team: Team | None = None, deleted: bool = False) -> ReviewQueueItem:
        queue = ReviewQueue.objects.create(team=team or self.team, name="Support QA", created_by=self.user)
        return ReviewQueueItem.objects.create(
            team=team or self.team, queue=queue, trace_id=TRACE_ID, created_by=self.user, deleted=deleted
        )

    def test_reads_review_scores_and_queue(self) -> None:
        self.user.first_name = "Ada"
        self.user.save()
        review = self._review()
        self._score(review, name="Tone", kind="numeric", config={}, numeric_value=Decimal("4.500000"))
        self._score(
            review,
            name="Accuracy",
            kind="categorical",
            config={"options": [{"key": "good", "label": "Good"}]},
            categorical_values=["good"],
        )
        item = self._queue_item()
        review.refresh_from_db()
        assert review.updated_at is not None

        assert load_trace_review_state(self.team, self.user, TRACE_ID) == TraceReviewState(
            review=HumanReview(
                reviewed_by="Ada",
                reviewed_at=review.updated_at,
                comment="Looks right",
                scores=(ReviewScore(name="Accuracy", value="Good"), ReviewScore(name="Tone", value="4.5")),
            ),
            queue=QueueAssignment(queue_id=str(item.queue_id), queue_name="Support QA", item_id=str(item.id)),
        )

    def test_nothing_for_an_unknown_trace(self) -> None:
        assert load_trace_review_state(self.team, self.user, "unknown") == NOTHING

    def test_reviewer_removed(self) -> None:
        review = self._review()
        review.reviewed_by = None
        review.save()

        state = load_trace_review_state(self.team, self.user, TRACE_ID)

        assert state.review is not None and state.review.reviewed_by is None

    @parameterized.expand(["deleted review", "deleted queue item", "deleted queue", "another team's rows"])
    def test_ignores_deleted_and_foreign_rows(self, case: str) -> None:
        if case == "deleted review":
            self._review(deleted=True)
        elif case == "deleted queue item":
            self._queue_item(deleted=True)
        elif case == "deleted queue":
            ReviewQueue.objects.filter(pk=self._queue_item().queue_id).update(deleted=True)
        else:
            other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
            self._review(team=other_team)
            self._queue_item(team=other_team)

        assert load_trace_review_state(self.team, self.user, TRACE_ID) == NOTHING

    @parameterized.expand([("review", False), ("queue", False), ("review", True), ("queue", True)])
    def test_hides_what_the_viewer_may_not_see_unless_they_administer_the_organization(
        self, blocked: str, is_admin: bool
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        review = self._review()
        item = self._queue_item()
        member = User.objects.create_and_join(
            self.organization,
            "member@example.com",
            "testtest",
            level=OrganizationMembership.Level.ADMIN if is_admin else OrganizationMembership.Level.MEMBER,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=str(review.id) if blocked == "review" else str(item.queue_id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
        )

        state = load_trace_review_state(self.team, member, TRACE_ID)

        hidden = not is_admin
        assert (state.review is None, state.queue is None) == (
            hidden and blocked == "review",
            hidden and blocked == "queue",
        )


class TestLoadTraceReviewStates(BaseTest):
    def _review(self, trace_id: str, *, deleted: bool = False) -> TraceReview:
        return TraceReview.objects.create(
            team=self.team, trace_id=trace_id, comment=f"On {trace_id}", created_by=self.user, deleted=deleted
        )

    def _queue_item(self, trace_id: str, queue: ReviewQueue) -> ReviewQueueItem:
        return ReviewQueueItem.objects.create(team=self.team, queue=queue, trace_id=trace_id, created_by=self.user)

    def test_each_requested_trace_gets_the_state_the_single_read_gives(self) -> None:
        queue = ReviewQueue.objects.create(team=self.team, name="Support QA", created_by=self.user)
        self._review("reviewed")
        self._review("gone", deleted=True)
        self._queue_item("queued", queue)
        trace_ids = ["reviewed", "queued", "neither", "gone"]

        states = load_trace_review_states(self.team, self.user, trace_ids)

        assert states == {trace_id: load_trace_review_state(self.team, self.user, trace_id) for trace_id in trace_ids}
        assert states["reviewed"].review is not None and states["reviewed"].queue is None
        assert states["queued"].review is None and states["queued"].queue is not None
        assert states["neither"] == NOTHING
        assert states["gone"] == NOTHING

    def test_no_ids_runs_no_query(self) -> None:
        with CaptureQueriesContext(connection) as queries:
            assert load_trace_review_states(self.team, self.user, []) == {}

        assert len(queries) == 0

    def test_repeated_ids_give_one_entry(self) -> None:
        self._review("reviewed")

        states = load_trace_review_states(self.team, self.user, ["reviewed", "reviewed"])

        assert list(states) == ["reviewed"]
        assert states["reviewed"].review is not None

    def test_query_count_does_not_grow_with_the_number_of_traces(self) -> None:
        queue = ReviewQueue.objects.create(team=self.team, name="Support QA", created_by=self.user)
        trace_ids = [f"trace-{n}" for n in range(30)]
        for trace_id in trace_ids:
            self._review(trace_id)
            self._queue_item(trace_id, queue)

        with CaptureQueriesContext(connection) as few:
            load_trace_review_states(self.team, self.user, trace_ids[:3])
        with CaptureQueriesContext(connection) as many:
            states = load_trace_review_states(self.team, self.user, trace_ids)

        assert len(many) == len(few)
        assert all(state.review is not None and state.queue is not None for state in states.values())

    def test_hides_what_the_viewer_may_not_see_per_trace(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        blocked_review = self._review("blocked-review")
        self._review("open-review")
        blocked_queue = ReviewQueue.objects.create(team=self.team, name="Hidden", created_by=self.user)
        open_queue = ReviewQueue.objects.create(team=self.team, name="Open", created_by=self.user)
        self._queue_item("blocked-queue", blocked_queue)
        self._queue_item("open-queue", open_queue)
        member = User.objects.create_and_join(self.organization, "member@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        for resource_id in (str(blocked_review.id), str(blocked_queue.id)):
            AccessControl.objects.create(
                team=self.team,
                resource="llm_analytics",
                resource_id=resource_id,
                access_level="none",
                organization_member=membership,
            )
        trace_ids = ["blocked-review", "open-review", "blocked-queue", "open-queue"]

        states = load_trace_review_states(self.team, member, trace_ids)

        assert states == {trace_id: load_trace_review_state(self.team, member, trace_id) for trace_id in trace_ids}
        assert states["blocked-review"] == NOTHING
        assert states["blocked-queue"] == NOTHING
        assert states["open-review"].review is not None
        assert states["open-queue"].queue is not None
