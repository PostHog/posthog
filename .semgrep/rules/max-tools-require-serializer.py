# Test cases for max-tools-require-serializer rule
# This file is used by `semgrep --test` to verify the rule works correctly.
#
# Note: This rule only applies to files named max_tools.py, but semgrep's test
# framework runs tests against this .py file directly, so we test the patterns here.

from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.models import Experiment, FeatureFlag, Survey, Tag, TaggedItem

# ============================================================
# max-tools-direct-model-create (WARNING - should use serializer)
# ============================================================


def vulnerable_direct_create(team):
    # ruleid: max-tools-direct-model-create
    flag = FeatureFlag.objects.create(team=team, key="test-flag", name="Test Flag")
    return flag


def vulnerable_direct_create_multiline(self, flag_schema, filters):
    # ruleid: max-tools-direct-model-create
    FeatureFlag.objects.create(
        team=self._team,
        created_by=self._user,
        key=flag_schema.key,
        name=flag_schema.name,
        active=flag_schema.active,
        filters=filters,
    )


# ============================================================
# OK cases - should NOT trigger the rule
# ============================================================


def safe_using_serializer(data, request):
    # Using serializer - correct pattern
    # ok: max-tools-direct-model-create
    serializer = FeatureFlagSerializer(data=data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    flag = serializer.save()
    return flag


def safe_different_model(team_id):
    # Different model not in the list
    # ok: max-tools-direct-model-create
    Tag.objects.create(name="test-tag", team_id=team_id)


def safe_tagged_item(tag, flag):
    # TaggedItem not in list - no dedicated serializer
    # ok: max-tools-direct-model-create
    TaggedItem.objects.create(tag=tag, feature_flag=flag)


def safe_experiment_not_in_list(team):
    # Experiment not in list yet
    # ok: max-tools-direct-model-create
    Experiment.objects.create(team=team, name="test")


def safe_survey_not_in_list(team):
    # Survey not in list yet
    # ok: max-tools-direct-model-create
    Survey.objects.create(team=team, name="test")


def safe_get_or_create(team):
    # get_or_create is different
    # ok: max-tools-direct-model-create
    FeatureFlag.objects.get_or_create(team=team, key="test")


def safe_filter_and_get(team):
    # filter/get operations are fine
    # ok: max-tools-direct-model-create
    FeatureFlag.objects.filter(team=team, key="test")
    # ok: max-tools-direct-model-create
    FeatureFlag.objects.get(team=team, key="test")
