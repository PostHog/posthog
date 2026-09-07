from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models import Comment, EntityDependency, Tag, Team
from posthog.models.entity_dependencies.registry import (
    DependencySource,
    EntityDependencyRegistryError,
    register_source,
    sync_instance_dependencies,
    unregister_source,
)
from posthog.models.entity_dependencies.sync import sync_dependencies
from posthog.models.entity_dependencies.types import Reference, SyncResult


class CommentReferenceSource(DependencySource[Comment]):
    entity_type = "test_comment"
    model = Comment

    def extract_references(self, instance: Comment) -> list[Reference]:
        if instance.deleted:
            return []
        references: list[dict[str, Any]] = (instance.rich_content or {}).get("references", [])
        return [
            Reference(
                target_type=reference["type"],
                target_id=str(reference["id"]),
                role=reference.get("role", "mention"),
                path=f"references[{index}]",
            )
            for index, reference in enumerate(references)
        ]


class ExplodingCommentSource(DependencySource[Comment]):
    entity_type = "test_exploding_comment"
    model = Comment

    def extract_references(self, instance: Comment) -> list[Reference]:
        raise RuntimeError("extraction bug")


class ConflictingSource(DependencySource[Any]):
    def __init__(self, entity_type: str, model: type[Comment] | type[Tag]) -> None:
        self.entity_type = entity_type
        self.model = model

    def extract_references(self, instance: Any) -> list[Reference]:
        return []


def _cohort(cohort_id: int, role: str = "mention") -> dict[str, Any]:
    return {"type": "cohort", "id": cohort_id, "role": role}


class TestEntityDependencySync(BaseTest):
    def _stored_references(self, source_type: str, source_id: str) -> set[Reference]:
        rows = EntityDependency.objects.for_team(self.team.id).filter(source_type=source_type, source_id=source_id)
        return {Reference(target_type=r.target_type, target_id=r.target_id, role=r.role, path=r.path) for r in rows}

    def test_sync_dependencies_diffs_desired_against_stored_rows(self) -> None:
        audience = Reference(target_type="cohort", target_id="1", role="audience", path="trigger")
        branch = Reference(target_type="cohort", target_id="2", role="condition", path="actions[0]")
        other_branch = Reference(target_type="cohort", target_id="2", role="condition", path="actions[1]")

        result = sync_dependencies(
            team_id=self.team.id, source_type="hog_flow", source_id="flow-1", references=[audience, branch]
        )
        assert result == SyncResult(added=2, removed=0)
        assert self._stored_references("hog_flow", "flow-1") == {audience, branch}

        result = sync_dependencies(
            team_id=self.team.id, source_type="hog_flow", source_id="flow-1", references=[audience, branch]
        )
        assert result == SyncResult(added=0, removed=0)

        result = sync_dependencies(
            team_id=self.team.id, source_type="hog_flow", source_id="flow-1", references=[branch, other_branch]
        )
        assert result == SyncResult(added=1, removed=1)
        assert self._stored_references("hog_flow", "flow-1") == {branch, other_branch}

        result = sync_dependencies(team_id=self.team.id, source_type="hog_flow", source_id="flow-1", references=[])
        assert result == SyncResult(added=0, removed=2)
        assert self._stored_references("hog_flow", "flow-1") == set()

    def test_sync_dependencies_stores_rows_under_the_project_team_for_an_environment(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="staging")
        reference = Reference(target_type="cohort", target_id="1", role="audience")

        sync_dependencies(team_id=environment.id, source_type="hog_flow", source_id="flow-1", references=[reference])
        result = sync_dependencies(
            team_id=environment.id, source_type="hog_flow", source_id="flow-1", references=[reference]
        )

        assert result == SyncResult(added=0, removed=0)
        assert self._stored_references("hog_flow", "flow-1") == {reference}
        assert EntityDependency.objects.unscoped().filter(source_id="flow-1").values_list(
            "team_id", flat=True
        ).get() == (self.team.id)

    def test_sync_dependencies_only_touches_rows_of_the_given_source(self) -> None:
        reference = Reference(target_type="cohort", target_id="1", role="audience")
        sync_dependencies(team_id=self.team.id, source_type="hog_flow", source_id="flow-1", references=[reference])
        sync_dependencies(team_id=self.team.id, source_type="hog_flow", source_id="flow-2", references=[reference])

        sync_dependencies(team_id=self.team.id, source_type="hog_flow", source_id="flow-1", references=[])

        assert self._stored_references("hog_flow", "flow-1") == set()
        assert self._stored_references("hog_flow", "flow-2") == {reference}

    def test_saving_and_deleting_a_registered_source_keeps_rows_current(self) -> None:
        register_source(CommentReferenceSource())
        self.addCleanup(unregister_source, "test_comment")

        comment = Comment.objects.create(
            team=self.team, scope="Notebook", rich_content={"references": [_cohort(1, "audience"), _cohort(2)]}
        )
        assert self._stored_references("test_comment", str(comment.id)) == {
            Reference(target_type="cohort", target_id="1", role="audience", path="references[0]"),
            Reference(target_type="cohort", target_id="2", role="mention", path="references[1]"),
        }

        comment.rich_content = {"references": [_cohort(2)]}
        comment.save()
        assert self._stored_references("test_comment", str(comment.id)) == {
            Reference(target_type="cohort", target_id="2", role="mention", path="references[0]"),
        }

        comment.deleted = True
        comment.save()
        assert self._stored_references("test_comment", str(comment.id)) == set()

        comment.deleted = False
        comment.save()
        assert len(self._stored_references("test_comment", str(comment.id))) == 1

        comment_id = str(comment.id)
        comment.delete()
        assert self._stored_references("test_comment", comment_id) == set()

    def test_sync_instance_dependencies_repairs_rows_after_a_signal_bypassing_write(self) -> None:
        register_source(CommentReferenceSource())
        self.addCleanup(unregister_source, "test_comment")
        comment = Comment.objects.create(team=self.team, scope="Notebook", rich_content={"references": [_cohort(1)]})

        Comment.objects.filter(id=comment.id).update(rich_content={"references": [_cohort(1), _cohort(3)]})
        assert len(self._stored_references("test_comment", str(comment.id))) == 1

        comment.refresh_from_db()
        assert sync_instance_dependencies(comment) == SyncResult(added=1, removed=0)
        assert len(self._stored_references("test_comment", str(comment.id))) == 2

    @parameterized.expand(
        [
            ("same_entity_type_other_model", "test_comment", Tag),
            ("same_model_other_entity_type", "test_comment_again", Comment),
        ]
    )
    def test_registering_a_conflicting_source_raises(
        self, _name: str, entity_type: str, model: type[Comment] | type[Tag]
    ) -> None:
        register_source(CommentReferenceSource())
        self.addCleanup(unregister_source, "test_comment")

        with self.assertRaises(EntityDependencyRegistryError):
            register_source(ConflictingSource(entity_type, model))

    def test_registering_the_same_source_instance_twice_is_a_no_op(self) -> None:
        source = CommentReferenceSource()
        register_source(source)
        self.addCleanup(unregister_source, "test_comment")

        register_source(source)

        comment = Comment.objects.create(team=self.team, scope="Notebook", rich_content={"references": [_cohort(1)]})
        assert len(self._stored_references("test_comment", str(comment.id))) == 1

    @override_settings(TEST=False)
    def test_a_failing_signal_sync_does_not_block_the_source_write(self) -> None:
        register_source(ExplodingCommentSource())
        self.addCleanup(unregister_source, "test_exploding_comment")

        with patch("posthog.models.entity_dependencies.registry.capture_exception") as capture_exception:
            comment = Comment.objects.create(team=self.team, scope="Notebook", rich_content={"references": []})

        assert Comment.objects.filter(id=comment.id).exists()
        capture_exception.assert_called_once()
        assert isinstance(capture_exception.call_args.args[0], RuntimeError)
