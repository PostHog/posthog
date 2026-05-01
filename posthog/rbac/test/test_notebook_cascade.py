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
    _resolve_to_ac_pk,
    cascade_grants_for_notebook,
    walk_notebook_content_for_grants,
)
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

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
                {"type": "ph-recording-playlist", "attrs": {"playlistShortId": "PLAY0001"}},
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
                    ("session_recording_playlist", "PLAY0001"),
                    ("notebook", "BACK0001"),
                ]
            ),
        )

    def test_recording_playlist_extractor_prefers_playlist_short_id_with_id_fallback(self) -> None:
        # Real playlist nodes embed via `attrs.playlistShortId` (matching the URL form).
        # Older content shapes may have stored it under `attrs.id` — keep fallback support.
        prefer_playlist_short_id = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-recording-playlist",
                    "attrs": {"playlistShortId": "PSI00001", "id": "should-be-ignored"},
                }
            ],
        }
        self.assertEqual(
            walk_notebook_content_for_grants(prefer_playlist_short_id),
            [("session_recording_playlist", "PSI00001")],
        )

        fallback_to_id = {
            "type": "doc",
            "content": [{"type": "ph-recording-playlist", "attrs": {"id": "ID000001"}}],
        }
        self.assertEqual(
            walk_notebook_content_for_grants(fallback_to_id),
            [("session_recording_playlist", "ID000001")],
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
                {"type": "ph-customer-journey", "attrs": {"id": "cj-1"}},
                {"type": "ph-map", "attrs": {"id": "m-1"}},
                {"type": "ph-replay-timestamp", "attrs": {"id": "ts-1"}},
                # Person nodes don't grant access — the guest's notebook AC row covers
                # team-scoped person reads through the existing AC layer.
                {"type": "ph-person", "attrs": {"id": "p-1"}},
                {"type": "ph-person-feed", "attrs": {"id": "pf-1"}},
                {"type": "ph-person-properties", "attrs": {"id": "pp-1"}},
                {"type": "mention", "attrs": {"id": "u-1"}},
            ],
        }
        self.assertEqual(walk_notebook_content_for_grants(content), [])

    def test_group_nodes_emit_composite_grants(self) -> None:
        # ph-group / ph-group-properties / ph-related-groups all carry
        # { id: <group_key>, groupTypeIndex: <int> } and cascade as a composite
        # `<group_type_index>:<group_key>` URL id. The resolver translates to the
        # integer Group PK before writing the AC row.
        content = {
            "type": "doc",
            "content": [
                {"type": "ph-group", "attrs": {"id": "company-acme", "groupTypeIndex": 0}},
                {"type": "ph-group-properties", "attrs": {"id": "company-acme", "groupTypeIndex": 0}},
                {"type": "ph-related-groups", "attrs": {"id": "company-acme", "groupTypeIndex": 0}},
            ],
        }
        self.assertEqual(walk_notebook_content_for_grants(content), [("group", "0:company-acme")])

    def test_group_node_without_group_type_index_is_skipped(self) -> None:
        # Defensive: missing groupTypeIndex means the embed isn't actionable.
        content = {
            "type": "doc",
            "content": [{"type": "ph-group", "attrs": {"id": "company-acme"}}],
        }
        self.assertEqual(walk_notebook_content_for_grants(content), [])

    def test_cascade_table_size_pinned(self) -> None:
        # Regression guard: changing the cascade table size should be deliberate. Update
        # this number along with the entry. Counts every entry, not unique resource types.
        self.assertEqual(len(NOTEBOOK_NODE_CASCADE), 13)


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

    def test_cascade_writes_uuid_id_for_survey_and_eaf(self) -> None:
        # Survey + EAF use UUID PKs in URL form. The resolver must accept UUID-shaped
        # values, not just digit-only ones — otherwise these embeds get silently dropped.
        survey_uuid = "019ddd56-b432-0000-23d4-ea6314d06150"
        eaf_uuid = "019c5642-b516-0000-6c72-20ada14284ad"
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [
                    {"type": "ph-survey", "attrs": {"id": survey_uuid}},
                    {"type": "ph-early-access-feature", "attrs": {"id": eaf_uuid}},
                ],
            },
            short_id="NBC00006",
        )
        cascade_grants_for_notebook(
            notebook=notebook,
            membership=self.guest_membership,
            team=self.team,
            created_by=self.user,
        )
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership, resource="survey", resource_id=survey_uuid
            ).exists()
        )
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership,
                resource="early_access_feature",
                resource_id=eaf_uuid,
            ).exists()
        )

    def test_cascade_writes_recording_pk_for_session_id_embed(self) -> None:
        # SessionRecording URL form is `session_id`, but the AC layer addresses by
        # the UUID PK. The cascade resolves session_id → PK before writing the AC row
        # so the middleware's later lookup via `access_level_for_object` matches.
        session_id = "0195b7c5-1c8a-7000-aaaa-aaaaaaaaaaaa"
        from posthog.session_recordings.models.session_recording import SessionRecording

        rec = SessionRecording.objects.create(team=self.team, session_id=session_id)
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [{"type": "ph-recording", "attrs": {"id": session_id}}],
            },
            short_id="NBC00007",
        )
        cascade_grants_for_notebook(
            notebook=notebook,
            membership=self.guest_membership,
            team=self.team,
            created_by=self.user,
        )
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership,
                resource="session_recording",
                resource_id=str(rec.id),
            ).exists()
        )

    def test_cascade_skips_recording_when_session_id_not_in_team(self) -> None:
        # No recording row exists yet for this session_id (e.g. ingest hasn't fired).
        # Skip the cascade write rather than fabricate a row — the recording API will
        # 404 the guest until a recording materializes; that's the intended behavior.
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [{"type": "ph-recording", "attrs": {"id": "0195b7c5-1c8a-7000-aaaa-cccccccccccc"}}],
            },
            short_id="NBC00010",
        )
        written = cascade_grants_for_notebook(
            notebook=notebook,
            membership=self.guest_membership,
            team=self.team,
            created_by=self.user,
        )
        self.assertEqual(written, 0)
        self.assertFalse(
            AccessControl.objects.filter(
                organization_member=self.guest_membership, resource="session_recording"
            ).exists()
        )

    def test_cascade_writes_group_ac_row(self) -> None:
        # End-to-end: a notebook that embeds a group node writes a `(group, str(pk))`
        # AC row so the AC layer's `has_any_specific_access_for_resource("group", ...)`
        # returns true and the `groups/find` / `groups/related` resolvers stop 403'ing.
        from posthog.models.group.group import Group

        group = Group.objects.create(team=self.team, group_type_index=0, group_key="company-acme", version=1)
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [{"type": "ph-group", "attrs": {"id": "company-acme", "groupTypeIndex": 0}}],
            },
            short_id="NBC00011",
        )
        cascade_grants_for_notebook(
            notebook=notebook,
            membership=self.guest_membership,
            team=self.team,
            created_by=self.user,
        )
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership,
                resource="group",
                resource_id=str(group.pk),
            ).exists()
        )

    def test_cascade_resolves_playlist_short_id_to_pk(self) -> None:
        # Playlist node embeds the short_id; the resolver looks up the integer PK and
        # writes that into the AC table (the AC layer addresses by PK, not short_id).
        playlist = SessionRecordingPlaylist.objects.create(team=self.team, short_id="PSI00099", name="Test playlist")
        notebook = self._make_notebook(
            {
                "type": "doc",
                "content": [{"type": "ph-recording-playlist", "attrs": {"playlistShortId": "PSI00099"}}],
            },
            short_id="NBC00008",
        )
        cascade_grants_for_notebook(
            notebook=notebook,
            membership=self.guest_membership,
            team=self.team,
            created_by=self.user,
        )
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership,
                resource="session_recording_playlist",
                resource_id=str(playlist.pk),
            ).exists()
        )


class TestResolveToAcPk(BaseTest):
    """Coverage for `_resolve_to_ac_pk` — the URL-id-to-PK shim that decides which
    embedded references actually become AC rows. Important to keep tight: a too-loose
    resolver would write garbage rows; a too-strict one silently drops valid embeds."""

    def test_accepts_digit_url_id_for_generic_resources(self) -> None:
        self.assertEqual(_resolve_to_ac_pk("cohort", "42", self.team.id), "42")
        self.assertEqual(_resolve_to_ac_pk("feature_flag", "7", self.team.id), "7")
        self.assertEqual(_resolve_to_ac_pk("experiment", "9", self.team.id), "9")

    def test_accepts_uuid_url_id_for_generic_resources(self) -> None:
        # Survey + EAF use UUID PKs in URL form. Without UUID acceptance the cascade
        # silently dropped these embeds before — covered here.
        survey_uuid = "019ddd56-b432-0000-23d4-ea6314d06150"
        eaf_uuid = "019c5642-b516-0000-6c72-20ada14284ad"
        self.assertEqual(_resolve_to_ac_pk("survey", survey_uuid, self.team.id), survey_uuid)
        self.assertEqual(_resolve_to_ac_pk("early_access_feature", eaf_uuid, self.team.id), eaf_uuid)

    def test_rejects_non_numeric_non_uuid_for_generic_resources(self) -> None:
        # An unrecognized id shape stays unwritten rather than corrupting the AC table.
        self.assertIsNone(_resolve_to_ac_pk("cohort", "not-a-real-id", self.team.id))
        self.assertIsNone(_resolve_to_ac_pk("survey", "garbage", self.team.id))

    def test_session_recording_resolves_session_id_to_pk(self) -> None:
        # SessionRecording URL form is `session_id`; AC layer addresses by UUID PK.
        # The resolver writes the PK so the middleware's later `access_level_for_object`
        # lookup against `str(obj.id)` matches.
        from posthog.session_recordings.models.session_recording import SessionRecording

        session_id = "0195b7c5-1c8a-7000-aaaa-aaaaaaaaaaaa"
        rec = SessionRecording.objects.create(team=self.team, session_id=session_id)
        self.assertEqual(
            _resolve_to_ac_pk("session_recording", session_id, self.team.id),
            str(rec.id),
        )
        self.assertIsNone(_resolve_to_ac_pk("session_recording", "0195b7c5-1c8a-7000-aaaa-deadbeefdead", self.team.id))

    def test_session_recording_playlist_resolves_short_id_to_pk(self) -> None:
        playlist = SessionRecordingPlaylist.objects.create(team=self.team, short_id="PSI00077", name="X")
        self.assertEqual(
            _resolve_to_ac_pk("session_recording_playlist", "PSI00077", self.team.id),
            str(playlist.pk),
        )
        self.assertIsNone(_resolve_to_ac_pk("session_recording_playlist", "DOES_NOT_EXIST", self.team.id))

    def test_group_resolves_composite_id_to_pk(self) -> None:
        # The walker emits `<group_type_index>:<group_key>`; the resolver looks up
        # `(team, group_type_index, group_key)` and returns the integer Group PK.
        from posthog.models.group.group import Group

        group = Group.objects.create(team=self.team, group_type_index=0, group_key="company-acme", version=1)
        self.assertEqual(_resolve_to_ac_pk("group", "0:company-acme", self.team.id), str(group.pk))
        # Missing group → no AC row written.
        self.assertIsNone(_resolve_to_ac_pk("group", "0:does-not-exist", self.team.id))
        # Malformed composite id → defensively rejected (no colon, non-numeric index, empty key).
        self.assertIsNone(_resolve_to_ac_pk("group", "company-acme", self.team.id))
        self.assertIsNone(_resolve_to_ac_pk("group", "abc:company-acme", self.team.id))
        self.assertIsNone(_resolve_to_ac_pk("group", "0:", self.team.id))
