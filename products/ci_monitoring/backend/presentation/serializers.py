"""DRF serializers for ci_monitoring."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade import contracts


class RepoSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.Repo


class CIRunSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.CIRun


class QuarantineSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.Quarantine


class TestCaseSerializer(DataclassSerializer):
    quarantine = QuarantineSerializer(allow_null=True, read_only=True)

    class Meta:
        dataclass = contracts.TestCase


class TestExecutionSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.TestExecution


class MainStreakSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.MainStreak


class CIHealthSerializer(DataclassSerializer):
    repo = RepoSerializer(read_only=True)
    streak = MainStreakSerializer(read_only=True)

    class Meta:
        dataclass = contracts.CIHealth


# --- Input serializers ---


class CreateRepoInputSerializer(serializers.Serializer):
    repo_external_id = serializers.IntegerField(
        default=0, help_text="GitHub numeric repository ID (stable across renames). Defaults to 0 if unknown."
    )
    repo_full_name = serializers.CharField(help_text="Full repository name (e.g., 'PostHog/posthog')")
    default_branch = serializers.CharField(default="main", help_text="Default branch name")


class CreateQuarantineInputSerializer(serializers.Serializer):
    test_case_id = serializers.UUIDField(help_text="ID of the test case to quarantine")
    reason = serializers.CharField(help_text="Reason for quarantining this test")
    create_github_issue = serializers.BooleanField(
        default=True, help_text="Whether to auto-create a GitHub issue for tracking"
    )


class ResolveQuarantineInputSerializer(serializers.Serializer):
    resolved_by_id = serializers.IntegerField(read_only=True)
