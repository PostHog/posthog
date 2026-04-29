"""Tests for the notebook embedded-node AC cascade.

The walker test cases cover the full `NOTEBOOK_NODE_CASCADE` table — adding a new
node type to the table without an accompanying walker test will look like an
unintentional widening on review.
"""

from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.insight import Insight
from posthog.models.user import User
from posthog.rbac.guest_grants import create_grant
from posthog.rbac.notebook_cascade import (
    NOTEBOOK_NODE_CASCADE,
    cascade_grants_for_notebook,
    walk_notebook_content_for_grants,
)

from products.notebooks.backend.models import Notebook

from ee.models.rbac.access_control import AccessControl


class TestWalkNotebookContentForGrants(BaseTest):
    """Pure walker — no DB. Asserts the structural mapping table is honored."""

    def test_empty_or_missing_content_returns_empty(self) -> None:
        self.assertEqual(walk_notebook_content_for_grants(None), [])
        self.assertEqual(walk_notebook_content_for_grants({}), [])
        self.assertEqual(walk_notebook_content_for_grants({"type": "doc"}), [])
        self.assertEqual(walk_notebook_content_for_grants("not-a-dict"), [])  # type: ignore[arg-type]

    def test_ph_query_with_saved_insight_emits_insight_grant(self) -> None:
        content = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-query",
                    "attrs": {"query": {"kind": "SavedInsightNode", "shortId": "ABC12345"}},
                }
            ],
        }
        self.assertEqual(walk_notebook_content_for_grants(content), [("insight", "ABC12345")])

    def test_ph_query_with_inline_query_is_skipped(self) -> None:
        # Inline (non-saved) query nodes carry no insight reference — non-cascadeable. The
        # query rescoper handles those at request time, not at grant time.
        content = {
            "type": "doc",
            "content": [{"type": "ph-query", "attrs": {"query": {"kind": "HogQLQuery", "query": "SELECT 1"}}}],
        }
        self.assertEqual(walk_notebook_content_for_grants(content), [])

    def test_recording_cohort_flag_experiment_survey_emit_grants(self) -> None:
        content = {
            "type": "doc",
            "content": [
                {"type": "ph-recording", "attrs": {"id": "rec-1"}},
                {"type": "ph-cohort", "attrs": {"id": "42"}},
                {"type": "ph-feature-flag", "attrs": {"id": "7"}},
                {"type": "ph-feature-flag-code-example", "attrs": {"id": "8"}},
                {"type": "ph-experiment", "attrs": {"id": "9"}},
                {"type": "ph-survey", "attrs": {"id": "uuid-1"}},
                {"type": "ph-early-access-feature", "attrs": {"id": "uuid-2"}},
                {"type": "ph-recording-playlist", "attrs": {"id": "11"}},
                {"type": "ph-backlink", "attrs": {"id": "BACK0001"}},
            ],
        }
        self.assertEqual(
            walk_notebook_content_for_grants(content),
            sorted(
                [
                    ("session_recording", "rec-1"),
                    ("cohort", "42"),
                    ("feature_flag", "7"),
                    ("feature_flag", "8"),
                    ("experiment", "9"),
                    ("survey", "uuid-1"),
                    ("early_access_feature", "uuid-2"),
                    ("session_recording_playlist", "11"),
                    ("notebook", "BACK0001"),
                ]
            ),
        )

    def test_walker_recurses_into_nested_content(self) -> None:
        content = {
            "type": "doc",
            "content": [
                {
                    "type": "blockquote",
                    "content": [
                        {"type": "ph-cohort", "attrs": {"id": "1"}},
                        {
                            "type": "bulletList",
                            "content": [
                                {
                                    "type": "listItem",
                                    "content": [{"type": "ph-feature-flag", "attrs": {"id": "2"}}],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        self.assertEqual(
            walk_notebook_content_for_grants(content),
            sorted([("cohort", "1"), ("feature_flag", "2")]),
        )

    def test_walker_deduplicates(self) -> None:
        # Same node embedded twice in the same notebook → one entry.
        content = {
            "type": "doc",
            "content": [
                {"type": "ph-cohort", "attrs": {"id": "1"}},
                {"type": "ph-cohort", "attrs": {"id": "1"}},
            ],
        }
        self.assertEqual(walk_notebook_content_for_grants(content), [("cohort", "1")])

    def test_walker_skips_nodes_without_id(self) -> None:
        content = {
            "type": "doc",
            "content": [
                {"type": "ph-cohort", "attrs": {}},
                {"type": "ph-recording"},
                {"type": "ph-feature-flag", "attrs": {"id": ""}},
            ],
        }
        self.assertEqual(walk_notebook_content_for_grants(content), [])

    def test_non_cascadeable_node_types_are_ignored(self) -> None:
        # Inline-only / admin-only node types intentionally absent from the cascade table:
        # python kernel, hogql sandbox, latex, image, embed, task-create, llm-trace, etc.
        content = {
            "type": "doc",
            "content": [
                {"type": "ph-python", "attrs": {"id": "py-1"}},
                {"type": "ph-duck-sql", "attrs": {"id": "sql-1"}},
                {"type": "ph-hogql-sql", "attrs": {"id": "hogql-1"}},
                {"type": "ph-latex", "attrs": {"id": "tex-1"}},
                {"type": "ph-image", "attrs": {"id": "img-1"}},
                {"type": "ph-embed", "attrs": {"id": "emb-1"}},
                {"type": "ph-task-create", "attrs": {"id": "task-1"}},
                {"type": "ph-llm-trace", "attrs": {"id": "trace-1"}},
                {"type": "ph-issues", "attrs": {"id": "iss-1"}},
                {"type": "ph-usage-metrics", "attrs": {"id": "um-1"}},
                {"type": "ph-zendesk-tickets", "attrs": {"id": "z-1"}},
                {"type": "ph-support-tickets", "attrs": {"id": "s-1"}},
                {"type": "ph-related-groups", "attrs": {"id": "g-1"}},
                {"type": "ph-customer-journey", "attrs": {"id": "cj-1"}},
                {"type": "ph-map", "attrs": {"id": "m-1"}},
                {"type": "ph-replay-timestamp", "attrs": {"id": "ts-1"}},
                # Person/group nodes don't grant access — guest's notebook AC row covers
                # team-scoped person/group reads through the existing AC layer.
                {"type": "ph-person", "attrs": {"id": "p-1"}},
                {"type": "ph-group", "attrs": {"id": "gr-1"}},
                {"type": "ph-person-feed", "attrs": {"id": "pf-1"}},
                {"type": "ph-person-properties", "attrs": {"id": "pp-1"}},
                {"type": "ph-group-properties", "attrs": {"id": "gp-1"}},
                {"type": "mention", "attrs": {"id": "u-1"}},
            ],
        }
        self.assertEqual(walk_notebook_content_for_grants(content), [])

    def test_cascade_table_size_pinned(self) -> None:
        # Regression guard: changing the cascade table size should be deliberate. Update
        # this number along with the entry. Counts every entry, not unique resource types.
        self.assertEqual(len(NOTEBOOK_NODE_CASCADE), 10)


class TestCascadeGrantsForNotebook(BaseTest):
    """End-to-end: grant a notebook → AC rows are written for embedded resources."""

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}
        ]
        self.organization.save()

        self.guest_user = User.objects.create_user(
            email="cascade-guest@example.com", first_name="C", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

    def _make_notebook(self, content: dict, short_id: str = "NBC00001") -> Notebook:
        return Notebook.objects.create(team=self.team, title="N", short_id=short_id, content=content)

    def test_cascade_writes_insight_ac_row_for_saved_insight_short_id(self) -> None:
        insight = Insight.objects.create(team=self.team, name="Activation", short_id="INS00001")
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [
                    {"type": "ph-query", "attrs": {"query": {"kind": "SavedInsightNode", "shortId": "INS00001"}}}
                ],
            }
        )
        written = cascade_grants_for_notebook(
            notebook=notebook,
            membership=self.guest_membership,
            team=self.team,
            created_by=self.user,
        )
        self.assertEqual(written, 1)
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership,
                resource="insight",
                resource_id=str(insight.pk),
                access_level="viewer",
            ).exists()
        )

    def test_cascade_writes_notebook_backlink_ac_row(self) -> None:
        target = Notebook.objects.create(team=self.team, title="Linked", short_id="LNK00001")
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [{"type": "ph-backlink", "attrs": {"id": "LNK00001"}}],
            },
            short_id="NBC00002",
        )
        written = cascade_grants_for_notebook(
            notebook=notebook,
            membership=self.guest_membership,
            team=self.team,
            created_by=self.user,
        )
        self.assertEqual(written, 1)
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership,
                resource="notebook",
                resource_id=str(target.pk),
            ).exists()
        )

    def test_cascade_skips_ghost_references(self) -> None:
        # ph-query node references a saved insight that doesn't exist in this team — no
        # AC row written, no error raised. The walker emits the entry; the resolver drops it.
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [
                    {"type": "ph-query", "attrs": {"query": {"kind": "SavedInsightNode", "shortId": "GHOST001"}}}
                ],
            },
            short_id="NBC00003",
        )
        written = cascade_grants_for_notebook(
            notebook=notebook,
            membership=self.guest_membership,
            team=self.team,
            created_by=self.user,
        )
        self.assertEqual(written, 0)
        self.assertFalse(
            AccessControl.objects.filter(organization_member=self.guest_membership, resource="insight").exists()
        )

    def test_cascade_writes_pk_id_for_numeric_resources(self) -> None:
        # cohort/feature_flag/etc. embed by integer PK — pass through directly to the AC table.
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [
                    {"type": "ph-cohort", "attrs": {"id": "42"}},
                    {"type": "ph-feature-flag", "attrs": {"id": "7"}},
                ],
            },
            short_id="NBC00004",
        )
        cascade_grants_for_notebook(
            notebook=notebook,
            membership=self.guest_membership,
            team=self.team,
            created_by=self.user,
        )
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership, resource="cohort", resource_id="42"
            ).exists()
        )
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership, resource="feature_flag", resource_id="7"
            ).exists()
        )

    def test_create_grant_for_notebook_fires_cascade(self) -> None:
        # End-to-end: the existing `create_grant` entry point (used by invite acceptance)
        # picks up the cascade automatically when granting a notebook.
        insight = Insight.objects.create(team=self.team, name="A", short_id="INS00009")
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [
                    {"type": "ph-query", "attrs": {"query": {"kind": "SavedInsightNode", "shortId": "INS00009"}}}
                ],
            },
            short_id="NBC00005",
        )

        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=notebook.short_id,
            created_by=self.user,
        )

        # Notebook AC row + cascaded insight AC row.
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership, resource="notebook", resource_id=str(notebook.pk)
            ).exists()
        )
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership, resource="insight", resource_id=str(insight.pk)
            ).exists()
        )
