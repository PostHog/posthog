from django.apps import apps
from django.db.models.fields.reverse_related import ForeignObjectRel
from django.test import SimpleTestCase

from posthog.models.activity_logging.activity_log import common_field_exclusions, field_exclusions
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.manager import TeamScopedManager

KNOWN_UNSAFE = frozenset(
    {
        "DataQualityCheck.runs",
        "Experiment.experimentmetricsrecalculation",
        "KnowledgeLibrary.repository_links",
        "KnowledgeLibrary.source_links",
        "KnowledgeSource.chunks",
        "KnowledgeSource.documents",
        "KnowledgeSource.library_links",
        "User.account",
        "User.commentslackthread",
        "User.custompropertydefinition",
        "User.fieldnote",
        "User.filesystemhomefolder",
        "User.hogfunctionrevision",
        "User.knowledgesource",
        "User.parserrecipe",
        "User.pendingsourcecredential",
        "User.warehousecolumnannotation",
        "User.workloadtrustpolicy",
        "WebExperiment.experimentmetricsrecalculation",
    }
)


class TestActivityDiffReverseRelations(SimpleTestCase):
    def test_no_new_activity_diff_reads_a_team_scoped_reverse_relation(self) -> None:
        found = set()
        for model in apps.get_models():
            if not issubclass(model, ModelActivityMixin):
                continue
            excluded = set(field_exclusions.get(model.__name__, [])) | set(common_field_exclusions)  # type: ignore[call-overload]
            for field in model._meta.get_fields():
                # A reverse one-to-one reads through the base manager, which is never team scoped.
                if not isinstance(field, ForeignObjectRel) or field.one_to_one or field.name in excluded:
                    continue
                if isinstance(field.related_model._default_manager, TeamScopedManager):
                    found.add(f"{model.__name__}.{field.name}")

        added = sorted(found - KNOWN_UNSAFE)
        assert not added, (
            f"The activity diff reads these reverse relations through a team-scoped manager: {added}. "
            "A save outside a request, such as a Slack action or a Celery task, has no team context, so the "
            "diff raises TeamScopeError and the save fails. Add each to field_exclusions in "
            "posthog/models/activity_logging/activity_log.py."
        )
        fixed = sorted(KNOWN_UNSAFE - found)
        assert not fixed, f"These are no longer unsafe, so drop them from KNOWN_UNSAFE: {fixed}"
