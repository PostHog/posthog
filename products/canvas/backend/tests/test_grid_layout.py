from typing import Any, cast

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.canvas.backend import welcome
from products.canvas.backend.layout import (
    MAX_LAYOUT_PATCH_OPERATIONS,
    apply_layout_ops,
    default_layout,
    validate_layout,
)
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasHomePreference, CanvasState
from products.canvas.backend.presentation.views import CanvasViewSet
from products.canvas.backend.source import has_errors, validate_source_project
from products.canvas.backend.tests.test_canvas_api import CanvasAPIBaseTest
from products.canvas.backend.tests.test_component_store import COMPONENT_META
from products.tasks.backend.models import Channel


def layout(**overrides) -> dict[str, Any]:
    doc = default_layout()
    doc.update(overrides)
    return doc


def placement(**overrides) -> dict[str, Any]:
    base = {"id": "p1", "status": "pending", "x": 0, "y": 0, "w": 2, "h": 1}
    base.update(overrides)
    return base


class GridLayoutAPIBaseTest(CanvasAPIBaseTest):
    def _create_grid(self, **overrides) -> str:
        return self._create_canvas(kind="grid", name="My grid", **overrides)

    def _create_component(self, *, built: bool = True, **overrides) -> str:
        component_id = self._create_canvas(kind="component", name="Weather", **overrides)
        response = self._publish(component_id, self._project(component=COMPONENT_META))
        assert response.status_code == status.HTTP_200_OK, response.json()
        if built:
            # The build worker is mocked out, so mark the queued build ready by hand.
            with team_scope(self.team.id):
                build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=component_id)
                build.status = CanvasBuild.STATUS_READY
                build.artifact_object_prefix = f"canvas_artifact/team_{self.team.id}/{component_id}/{build.id}"
                build.save(update_fields=["status", "artifact_object_prefix"])
                Canvas.objects.for_team(self.team.id).filter(pk=component_id).update(published_build=build)
        return component_id

    def _publish_layout(self, canvas_id: str, doc: dict[str, Any] | None = None, **payload):
        return self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/layout/publish/",
            {"layout": doc or layout(), **payload},
            format="json",
        )

    def _patch_layout(self, canvas_id: str, operations: list[dict[str, Any]], expected: str | None, **payload):
        return self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/layout/patch/",
            {"operations": operations, "expected_current_version_id": expected, **payload},
            format="json",
        )

    def _get_layout(self, canvas_id: str):
        return self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/layout/")

    def _publish_component_version(self, component_id: str, *, config_schema: dict[str, Any]) -> str:
        meta = {**COMPONENT_META, "configSchema": config_schema}
        response = self._publish(component_id, self._project(component=meta))
        assert response.status_code == status.HTTP_200_OK, response.json()
        return cast(str, response.json()["current_version_id"])

    def _mark_head_build_ready(self, component_id: str) -> None:
        with team_scope(self.team.id):
            component = Canvas.objects.for_team(self.team.id).get(pk=component_id)
            build = CanvasBuild.objects.for_team(self.team.id).get(
                source_version_id=component.current_source_version_id
            )
            build.status = CanvasBuild.STATUS_READY
            build.artifact_object_prefix = f"canvas_artifact/team_{self.team.id}/{component_id}/{build.id}"
            build.save(update_fields=["status", "artifact_object_prefix"])
            Canvas.objects.for_team(self.team.id).filter(pk=component_id).update(published_build=build)


class TestGridLayoutApi(GridLayoutAPIBaseTest):
    def test_layout_publish_round_trips_without_queuing_a_build(self):
        grid_id = self._create_grid()
        component_id = self._create_component()
        self.enqueue.reset_mock()

        doc = layout(placements=[placement(status="live", component=component_id, config={"location": "Lisbon"})])
        response = self._publish_layout(grid_id, doc)
        assert response.status_code == status.HTTP_200_OK, response.json()
        version_id = response.json()["current_version_id"]

        read = self._get_layout(grid_id)
        assert read.status_code == status.HTTP_200_OK
        assert read.json()["layout"]["placements"][0]["component"] == component_id
        assert read.json()["current_version_id"] == version_id
        self.enqueue.assert_not_called()

    def test_unpublished_grid_returns_default_layout(self):
        grid_id = self._create_grid()
        read = self._get_layout(grid_id)
        assert read.status_code == status.HTTP_200_OK
        assert read.json()["layout"] == default_layout()
        assert read.json()["current_version_id"] is None

    def test_layout_endpoints_reject_non_grid_canvases(self):
        freeform_id = self._create_canvas()
        assert self._get_layout(freeform_id).status_code == status.HTTP_400_BAD_REQUEST
        response = self._publish_layout(freeform_id)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "wrong_canvas_kind"

    def test_source_rejects_grid_canvases(self):
        grid_id = self._create_grid()
        response = self.client.get(f"/api/projects/{self.team.id}/canvases/{grid_id}/source/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "wrong_canvas_kind"

    def test_guarded_publish_conflict(self):
        grid_id = self._create_grid()
        first = self._publish_layout(grid_id, expected_current_version_id=None)
        assert first.status_code == status.HTTP_200_OK
        stale = self._publish_layout(grid_id, expected_current_version_id=None)
        assert stale.status_code == status.HTTP_409_CONFLICT
        assert stale.json()["current_version_id"] == first.json()["current_version_id"]

    def test_patch_flow_draw_fill_move_remove(self):
        grid_id = self._create_grid()
        component_id = self._create_component()

        drawn = self._patch_layout(
            grid_id,
            [{"op": "add_placement", "placement": placement(prompt="weather for Lisbon")}],
            expected=None,
        )
        assert drawn.status_code == status.HTTP_200_OK, drawn.json()
        version = drawn.json()["current_version_id"]

        filled = self._patch_layout(
            grid_id,
            [
                {
                    "op": "update_placement",
                    "id": "p1",
                    "changes": {"status": "live", "component": component_id, "config": {"location": "Lisbon"}},
                }
            ],
            expected=version,
        )
        assert filled.status_code == status.HTTP_200_OK, filled.json()
        placed = filled.json()["layout"]["placements"][0]
        assert placed["status"] == "live"
        assert placed["prompt"] == "weather for Lisbon"

        moved = self._patch_layout(
            grid_id,
            [{"op": "update_placement", "id": "p1", "changes": {"x": 2, "y": 3}}],
            expected=filled.json()["current_version_id"],
        )
        assert moved.status_code == status.HTTP_200_OK

        removed = self._patch_layout(
            grid_id,
            [{"op": "remove_placement", "id": "p1"}],
            expected=moved.json()["current_version_id"],
        )
        assert removed.status_code == status.HTTP_200_OK
        assert removed.json()["layout"]["placements"] == []

    def test_patch_against_stale_version_conflicts(self):
        grid_id = self._create_grid()
        first = self._patch_layout(grid_id, [{"op": "add_placement", "placement": placement()}], expected=None)
        assert first.status_code == status.HTTP_200_OK
        stale = self._patch_layout(grid_id, [{"op": "remove_placement", "id": "p1"}], expected=None)
        assert stale.status_code == status.HTTP_409_CONFLICT

    def test_patch_unknown_placement_rejected(self):
        grid_id = self._create_grid()
        response = self._patch_layout(grid_id, [{"op": "remove_placement", "id": "ghost"}], expected=None)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert any(entry["code"] == "edit_target_missing" for entry in response.json()["diagnostics"])

    def test_patch_not_blocked_by_preexisting_invalid_placement(self):
        grid_id = self._create_grid()
        component_id = self._create_component()
        doc = layout(placements=[placement(status="live", component=component_id, config={"location": "Lisbon"})])
        published = self._publish_layout(grid_id, doc)
        assert published.status_code == status.HTTP_200_OK, published.json()
        version_id = published.json()["current_version_id"]
        # The component disappears after placement; the live placement is now
        # invalid through no fault of the layout's own edits.
        with team_scope(self.team.id):
            Canvas.objects.for_team(self.team.id).filter(pk=component_id).update(deleted=True)

        added = self._patch_layout(
            grid_id,
            [{"op": "add_placement", "placement": placement(id="p2", x=2)}],
            expected=version_id,
        )
        assert added.status_code == status.HTTP_200_OK, added.json()

        # A patch that introduces a problem of its own is still rejected.
        worsened = self._patch_layout(
            grid_id,
            [{"op": "add_placement", "placement": placement(id="p3", x=4, status="live")}],
            expected=added.json()["current_version_id"],
        )
        assert worsened.status_code == status.HTTP_400_BAD_REQUEST
        assert any(entry["code"] == "invalid_placement" for entry in worsened.json()["diagnostics"])

    def test_live_placement_requires_available_component(self):
        grid_id = self._create_grid()
        unpublished_id = self._create_canvas(kind="component", name="Empty component")
        doc = layout(placements=[placement(status="live", component=unpublished_id)])
        response = self._publish_layout(grid_id, doc)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert any(entry["code"] == "component_not_published" for entry in response.json()["diagnostics"])

    def test_live_placement_requires_ready_build(self):
        grid_id = self._create_grid()
        component_id = self._create_component(built=False)
        doc = layout(placements=[placement(status="live", component=component_id)])
        rejected = self._publish_layout(grid_id, doc)
        assert rejected.status_code == status.HTTP_400_BAD_REQUEST
        assert any(entry["code"] == "component_build_not_ready" for entry in rejected.json()["diagnostics"])
        # The same placement may wait in the generating state until the build is ready.
        staged = self._publish_layout(
            grid_id, layout(placements=[placement(status="generating", component=component_id)])
        )
        assert staged.status_code == status.HTTP_200_OK, staged.json()

    def test_component_in_anothers_personal_channel_is_not_placeable(self):
        with team_scope(self.team.id):
            other_personal = Channel.objects.create(
                team=self.team,
                name="them",
                channel_type=Channel.ChannelType.PERSONAL,
                created_by=None,
            )
            component = Canvas.objects.create(
                team=self.team, channel=other_personal, name="Private", kind=Canvas.KIND_COMPONENT
            )
        grid_id = self._create_grid()
        doc = layout(placements=[placement(status="live", component=str(component.id))])
        response = self._publish_layout(grid_id, doc)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert any(entry["code"] == "component_not_found" for entry in response.json()["diagnostics"])

    def test_config_violating_component_schema_rejected(self):
        grid_id = self._create_grid()
        component_id = self._create_component()
        doc = layout(placements=[placement(status="live", component=component_id, config={"location": 5})])
        response = self._publish_layout(grid_id, doc)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert any(entry["code"] == "placement_config_invalid" for entry in response.json()["diagnostics"])

    @parameterized.expand(
        [("publish", "layout__placements__non_field_errors"), ("patch", "operations__non_field_errors")]
    )
    def test_oversized_layout_writes_are_rejected_at_the_request_boundary(self, route: str, rejected_attr: str):
        # Per-placement and per-operation validation is itself work an attacker
        # pays nothing for, so the count has to be refused before any of it runs
        # rather than reported as a layout diagnostic afterwards.
        grid_id = self._create_grid()
        if route == "publish":
            doc = layout(placements=[placement(id=f"p{index}") for index in range(400)])
            response = self._publish_layout(grid_id, doc)
        else:
            operations = [
                {"op": "add_placement", "placement": placement(id=f"p{index}")}
                for index in range(MAX_LAYOUT_PATCH_OPERATIONS + 1)
            ]
            response = self._patch_layout(grid_id, operations, expected=None)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "max_length", response.json()
        assert response.json()["attr"] == rejected_attr, response.json()

    def test_pinned_version_is_validated_against_its_own_config_schema(self):
        grid_id = self._create_grid()
        component_id = self._create_component()
        pinned_version = self._publish_component_version(
            component_id, config_schema={"type": "object", "properties": {"location": {"type": "string"}}}
        )
        # The component republishes with an incompatible contract; the pinned
        # placement still renders the version it named, so it answers to that
        # version's schema and not to the head's.
        self._publish_component_version(
            component_id,
            config_schema={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
        )
        doc = layout(
            placements=[
                placement(
                    status="generating",
                    component=component_id,
                    version=pinned_version,
                    config={"location": "Lisbon"},
                )
            ]
        )
        response = self._publish_layout(grid_id, doc)
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_live_placement_pinned_to_a_version_without_a_ready_build_rejected(self):
        grid_id = self._create_grid()
        component_id = self._create_component()
        # The pinned version's own build never went ready; only the head's did,
        # which is what a placement pinned to the older version cannot render.
        pinned_version = self._publish_component_version(
            component_id, config_schema={"type": "object", "properties": {"location": {"type": "string"}}}
        )
        self._publish_component_version(
            component_id, config_schema={"type": "object", "properties": {"location": {"type": "string"}}}
        )
        self._mark_head_build_ready(component_id)

        doc = layout(placements=[placement(status="live", component=component_id, version=pinned_version)])
        response = self._publish_layout(grid_id, doc)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert any(entry["code"] == "component_build_not_ready" for entry in response.json()["diagnostics"])

    def test_placement_pinned_to_an_unknown_version_rejected(self):
        grid_id = self._create_grid()
        component_id = self._create_component()
        doc = layout(
            placements=[
                placement(status="generating", component=component_id, version="00000000-0000-4000-8000-000000000000")
            ]
        )
        response = self._publish_layout(grid_id, doc)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert any(entry["code"] == "component_version_not_found" for entry in response.json()["diagnostics"])

    @parameterized.expand(
        [
            ("config_omitted", None, status.HTTP_400_BAD_REQUEST),
            ("config_empty", {}, status.HTTP_400_BAD_REQUEST),
            ("config_complete", {"location": "Lisbon"}, status.HTTP_200_OK),
        ]
    )
    def test_required_config_properties_are_enforced(self, _name: str, config: dict[str, Any] | None, expected: int):
        # Omitting `config` hands the component the same empty object as
        # `config: {}`, so both must answer for the schema's required keys.
        grid_id = self._create_grid()
        component_id = self._create_component()
        self._publish_component_version(
            component_id,
            config_schema={
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        )
        overrides: dict[str, Any] = {"status": "generating", "component": component_id}
        if config is not None:
            overrides["config"] = config
        response = self._publish_layout(grid_id, layout(placements=[placement(**overrides)]))
        assert response.status_code == expected, response.json()

    def test_placement_size_outside_component_contract_is_advisory(self):
        # The user sizes their own grid; a size outside the component's
        # suggested range must not block the publish.
        grid_id = self._create_grid()
        component_id = self._create_component()
        meta = {**COMPONENT_META, "size": {"defaultW": 2, "defaultH": 1, "minW": 2, "minH": 1, "maxW": 3}}
        response = self._publish(component_id, self._project(component=meta))
        assert response.status_code == status.HTTP_200_OK
        doc = layout(placements=[placement(status="live", component=component_id, w=1)])
        published = self._publish_layout(grid_id, doc)
        assert published.status_code == status.HTTP_200_OK, published.json()


class TestHomeProvisioning(GridLayoutAPIBaseTest):
    def _home(self):
        return self.client.post(f"/api/projects/{self.team.id}/canvases/home/")

    def test_home_provisions_once_and_is_idempotent(self):
        first = self._home()
        assert first.status_code == status.HTTP_201_CREATED, first.json()
        assert first.json()["kind"] == "grid"
        second = self._home()
        assert second.status_code == status.HTTP_200_OK
        assert second.json()["id"] == first.json()["id"]
        with team_scope(self.team.id):
            assert CanvasHomePreference.objects.for_team(self.team.id).filter(user=self.user).count() == 1

    def test_home_reprovisions_after_canvas_deletion(self):
        first = self._home()
        self.client.delete(f"/api/projects/{self.team.id}/canvases/{first.json()['id']}/")
        replacement = self._home()
        assert replacement.status_code == status.HTTP_201_CREATED
        assert replacement.json()["id"] != first.json()["id"]

    @parameterized.expand([("without_github", False), ("with_github", True)])
    def test_home_seeds_welcome_checklist(self, _name: str, github_connected: bool):
        if github_connected:
            Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})
        first = self._home()
        assert first.status_code == status.HTTP_201_CREATED, first.json()
        home_id = first.json()["id"]

        read = self._get_layout(home_id)
        assert read.status_code == status.HTTP_200_OK
        placements = read.json()["layout"]["placements"]
        assert len(placements) == 1
        seeded = placements[0]
        assert seeded["status"] == "live"
        assert (seeded["w"], seeded["h"]) == (2, 5)

        with team_scope(self.team.id):
            component = Canvas.objects.for_team(self.team.id).get(id=seeded["component"])
            assert component.kind == Canvas.KIND_COMPONENT
            assert component.name == welcome.WELCOME_COMPONENT_NAME
            assert component.channel_id == Canvas.objects.for_team(self.team.id).get(id=home_id).channel_id
            assert component.current_source_version is not None
            assert component.current_source_version.component_meta is not None
            state = CanvasState.objects.for_team(self.team.id).get(
                canvas=component, scope=CanvasState.SCOPE_USER, user=self.user, key=welcome.WELCOME_STATE_KEY
            )
        assert state.value == {"download-desktop": True, "connect-github": github_connected}

    def test_losing_a_provisioning_race_returns_the_winners_home(self):
        # Two first opens (two tabs, or desktop plus web) both miss the pointer.
        # The loser must hand back the winner's canvas instead of provisioning a
        # second Home that nothing points at.
        first = self._home()
        assert first.status_code == status.HTTP_201_CREATED, first.json()
        unlocked_read = CanvasViewSet._home_canvas_for
        reads = {"count": 0}

        def missed_once(view: CanvasViewSet, user: User) -> Canvas | None:
            reads["count"] += 1
            return None if reads["count"] == 1 else unlocked_read(view, user)

        with patch.object(CanvasViewSet, "_home_canvas_for", missed_once):
            raced = self._home()
        assert raced.status_code == status.HTTP_200_OK, raced.json()
        assert raced.json()["id"] == first.json()["id"]
        with team_scope(self.team.id):
            assert Canvas.objects.for_team(self.team.id).filter(kind=Canvas.KIND_GRID, deleted=False).count() == 1

    def test_home_provisions_even_when_seeding_fails(self):
        with patch(
            "products.canvas.backend.presentation.views.seed_home_canvas", side_effect=RuntimeError("storage down")
        ):
            response = self._home()
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        read = self._get_layout(response.json()["id"])
        assert read.status_code == status.HTTP_200_OK
        assert read.json()["layout"]["placements"] == []


class TestWelcomeChecklistProject(SimpleTestCase):
    def test_seed_project_passes_source_validation(self):
        diagnostics = validate_source_project(welcome.welcome_checklist_project(), kind="component")
        assert not has_errors(diagnostics), diagnostics


class TestLayoutValidation(CanvasAPIBaseTest):
    @parameterized.expand(
        [
            ("wrong_schema_version", layout(schemaVersion=2), "unsupported_schema_version"),
            ("bad_columns", layout(grid={"columns": 5, "rowHeight": 96, "gap": 8}), "invalid_grid"),
            (
                "overlap",
                layout(placements=[placement(), placement(id="p2", x=1)]),
                "placements_overlap",
            ),
            (
                "past_grid_edge",
                layout(placements=[placement(x=5, w=2)]),
                "invalid_placement",
            ),
            (
                "duplicate_ids",
                layout(placements=[placement(), placement(y=5)]),
                "duplicate_placement_id",
            ),
            (
                "live_without_component",
                layout(placements=[placement(status="live")]),
                "invalid_placement",
            ),
            (
                "too_many_placements",
                layout(placements=[placement(id=f"p{i}", x=i % 6, y=i // 6) for i in range(25)]),
                "too_many_placements",
            ),
        ]
    )
    def test_invalid_layouts_produce_error(self, _name, doc, expected_code):
        diagnostics = validate_layout(doc)
        assert expected_code in [entry["code"] for entry in diagnostics], diagnostics

    def test_apply_ops_leaves_input_untouched(self):
        original = layout(placements=[placement()])
        edited, diagnostics = apply_layout_ops(original, [{"op": "remove_placement", "id": "p1"}])
        assert diagnostics == []
        assert edited["placements"] == []
        assert original["placements"] == [placement()]

    def test_oversized_layout_is_not_walked_for_overlaps(self):
        # Overlap detection compares every placement against every earlier one,
        # so an over-cap document must be rejected before that scan runs.
        doc = layout(placements=[placement(id=f"p{index}") for index in range(400)])
        diagnostics = validate_layout(doc)
        assert [entry["code"] for entry in diagnostics] == ["too_many_placements"]

    def test_apply_ops_rejects_growing_past_the_placement_cap(self):
        operations = [{"op": "add_placement", "placement": placement(id=f"p{index}")} for index in range(40)]
        _, diagnostics = apply_layout_ops(default_layout(), operations)
        assert any(entry["code"] == "too_many_placements" for entry in diagnostics)

    def test_layout_larger_than_the_persisted_cap_is_rejected(self):
        doc = layout(placements=[placement(config={"blob": "x" * 300_000})])
        diagnostics = validate_layout(doc)
        assert any(entry["code"] == "layout_too_large" for entry in diagnostics)
