from django.test import SimpleTestCase, TestCase

from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.canvas.backend import teaching
from products.canvas.backend.models import Canvas
from products.canvas.backend.source import has_errors, validate_source_project
from products.canvas.backend.tests.test_canvas_api import CanvasAPIBaseTest
from products.tasks.backend.models import Channel


class TestTeachingTourProject(SimpleTestCase):
    def test_seed_project_passes_source_validation(self):
        diagnostics = validate_source_project(teaching.teaching_tour_project(), kind="freeform")
        assert not has_errors(diagnostics), diagnostics


class TestReservedTemplateIds(CanvasAPIBaseTest):
    def test_a_user_cannot_claim_the_seeded_template_id(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/",
            {
                "name": "Impostor tour",
                "channel_id": str(self.channel.id),
                "template_id": teaching.TEACHING_CANVAS_TEMPLATE_ID,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertIn("reserved", str(response.json()))


class TestSeedTeachingCanvas(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Northwind")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="ada@northwind.example", distinct_id="ada-distinct")
        # Seeding runs inside the channels viewset, so give it the same ambient scope.
        self.enterContext(team_scope(self.team.id))
        self.channel = Channel.objects.create(
            team=self.team,
            name=Channel.GENERAL_CHANNEL_NAME,
            channel_type=Channel.ChannelType.PUBLIC,
            system_role=Channel.SystemRole.GENERAL,
            created_by=self.user,
        )

    def _seed(self, *, refresh: bool = False) -> object:
        return teaching.seed_teaching_canvas(
            team_id=self.team.id, channel_id=self.channel.id, user=self.user, refresh=refresh
        )

    def _tours(self):
        return Canvas.objects.for_team(self.team.id).filter(
            channel_id=self.channel.id, template_id=teaching.TEACHING_CANVAS_TEMPLATE_ID
        )

    def test_a_first_seed_publishes_a_pinned_tour(self):
        canvas_id = self._seed()

        canvas = self._tours().get()
        self.assertEqual(canvas.id, canvas_id)
        self.assertIsNotNone(canvas.pinned_at)
        self.assertIsNotNone(canvas.current_source_version_id)

    def test_a_second_seed_reuses_the_first_tour(self):
        first = self._seed()

        second = self._seed()

        self.assertEqual(first, second)
        self.assertEqual(self._tours().count(), 1)

    def test_a_deleted_tour_stays_deleted(self):
        self._seed()
        self._tours().update(deleted=True)

        self.assertIsNone(self._seed())
        self.assertEqual(self._tours().count(), 1)

    def test_a_refreshing_seed_revives_a_deleted_tour_and_republishes_it(self):
        first = self._seed()
        self._tours().update(deleted=True)

        self.assertEqual(self._seed(refresh=True), first)
        canvas = self._tours().get()
        self.assertFalse(canvas.deleted)
        self.assertIsNotNone(canvas.pinned_at)
        self.assertIsNotNone(canvas.current_source_version_id)

    def test_a_tour_whose_publish_failed_heals_on_the_next_seed(self):
        canvas_id = self._seed()
        canvas = self._tours().get()
        canvas.current_source_version = None
        canvas.save(update_fields=["current_source_version"])

        self.assertEqual(self._seed(), canvas_id)
        canvas.refresh_from_db()
        self.assertIsNotNone(canvas.current_source_version_id)
