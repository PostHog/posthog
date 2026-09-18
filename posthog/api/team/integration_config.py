"""Serializers and handlers for product-specific project settings."""

from typing import Any, cast

from django.db import transaction

import posthoganalytics
from rest_framework import exceptions, request, response, serializers

from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.models.team.extensions import get_or_create_team_extension

from products.feature_flags.backend.models.evaluation_context import EvaluationContext, normalize_context_name
from products.logs.backend.models import TeamLogsConfig
from products.tracing.backend.facade.team_extension import TeamTracingConfig


def _validate_unique_attribute_keys(value: list[str]) -> list[str]:
    # The child CharField already trims whitespace and rejects blanks; only
    # cross-item uniqueness needs checking here.
    if len(set(value)) != len(value):
        raise serializers.ValidationError("Attribute keys must be unique.")
    return value


class TeamLogsConfigSerializer(serializers.ModelSerializer):
    logs_distinct_id_attribute_key = serializers.CharField(
        read_only=True,
        help_text=(
            "Legacy single-key alias — always the first entry of "
            "`logs_distinct_id_attribute_keys`. Read-only; write the plural field instead."
        ),
    )
    logs_distinct_id_attribute_keys = serializers.ListField(
        # trim_whitespace is the DRF default, but the uniqueness validator below
        # depends on it — spell it out so it can't drift silently.
        child=serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True),
        allow_empty=False,
        max_length=10,
        help_text=(
            "Log attribute keys whose values should match a person's distinct_id — a log "
            "links to a person when any of these attributes equals one of their distinct IDs. "
            "Used by the person profile Logs tab and the `query-logs` MCP tool. Defaults to "
            "['posthogDistinctId'] — the convention documented at "
            "https://posthog.com/docs/logs/link-session-replay and the key the "
            "posthog-js / posthog-react-native SDKs auto-attach. Add keys only if your "
            "pipeline emits the person identifier under different attributes."
        ),
    )
    logs_session_id_attribute_keys = serializers.ListField(
        # trim_whitespace is the DRF default, but the uniqueness validator below
        # depends on it — spell it out so it can't drift silently.
        child=serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True),
        allow_empty=False,
        max_length=10,
        help_text=(
            "Ordered list of log attribute keys whose values hold the PostHog session ID. "
            "Detection checks keys in order, then falls back to common session ID attribute "
            "conventions; the first key with a value wins. Defaults to ['sessionId'] — the "
            "convention documented at https://posthog.com/docs/logs/link-session-replay and "
            "the key the posthog-js / posthog-react-native SDKs auto-attach. Add keys only "
            "if your pipeline emits the session ID under different attributes."
        ),
    )
    logs_pattern_message_keys = serializers.ListField(
        child=serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True),
        allow_empty=True,
        max_length=10,
        help_text=(
            "Ordered list of top-level JSON keys whose value is the message text that log "
            "patterns are derived from. Keys are matched literally at the top level of the log "
            "body; a dot in a key is part of the key name, not a path into nested objects. "
            "Selection checks keys in order; the first key whose value is a non-empty string "
            "wins. Defaults to ['message', 'msg', 'event']. An empty list "
            "turns message extraction off, so JSON log bodies group by their key set instead. "
            "The stored log body is never changed by this setting."
        ),
    )

    class Meta:
        model = TeamLogsConfig
        fields = [
            "logs_distinct_id_attribute_key",
            "logs_distinct_id_attribute_keys",
            "logs_session_id_attribute_keys",
            "logs_pattern_message_keys",
        ]

    def validate_logs_distinct_id_attribute_keys(self, value: list[str]) -> list[str]:
        return _validate_unique_attribute_keys(value)

    def validate_logs_session_id_attribute_keys(self, value: list[str]) -> list[str]:
        return _validate_unique_attribute_keys(value)

    def validate_logs_pattern_message_keys(self, value: list[str]) -> list[str]:
        return _validate_unique_attribute_keys(value)

    def update(self, instance: TeamLogsConfig, validated_data: dict) -> TeamLogsConfig:
        # Keep the legacy single-key column in sync so pre-plural readers stay coherent.
        keys = validated_data.get("logs_distinct_id_attribute_keys")
        if keys:
            validated_data["logs_distinct_id_attribute_key"] = keys[0]
        return super().update(instance, validated_data)


class TeamTracingConfigSerializer(serializers.ModelSerializer):
    tracing_distinct_id_attribute_keys = serializers.ListField(
        # trim_whitespace is the DRF default, but the uniqueness validator below
        # depends on it — spell it out so it can't drift silently.
        child=serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True),
        allow_empty=False,
        max_length=10,
        help_text=(
            "Span or resource attribute keys whose values should match a person's distinct_id — "
            "a span links to a person when any of these attributes holds one of their distinct "
            "IDs. Defaults to ['posthogDistinctId'], the key the posthog-js / "
            "posthog-react-native SDKs attach to the OTel signals they emit. Add keys only if "
            "your pipeline emits the person identifier under different attributes."
        ),
    )
    tracing_session_id_attribute_keys = serializers.ListField(
        # trim_whitespace is the DRF default, but the uniqueness validator below
        # depends on it — spell it out so it can't drift silently.
        child=serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True),
        allow_empty=False,
        max_length=10,
        help_text=(
            "Ordered list of span or resource attribute keys whose values hold the PostHog "
            "session ID. Detection checks keys in order, then falls back to common session ID "
            "attribute conventions; the first key with a value wins. Defaults to ['sessionId'], "
            "the key the posthog-js / posthog-react-native SDKs attach to the OTel signals they "
            "emit. Add keys only if your pipeline emits the session ID under different attributes."
        ),
    )

    class Meta:
        model = TeamTracingConfig
        fields = [
            "tracing_distinct_id_attribute_keys",
            "tracing_session_id_attribute_keys",
        ]

    def validate_tracing_distinct_id_attribute_keys(self, value: list[str]) -> list[str]:
        return _validate_unique_attribute_keys(value)

    def validate_tracing_session_id_attribute_keys(self, value: list[str]) -> list[str]:
        return _validate_unique_attribute_keys(value)


def handle_tracing_config(request: request.Request, team: Team) -> response.Response:
    """Shared handler for the tracing_config action — exposed under both the team/environment
    and project routers so the canonical /api/projects/ URL resolves alongside the legacy
    /api/environments/ alias. Both endpoints operate on the env-scoped TeamTracingConfig
    keyed by team_id."""
    config = get_or_create_team_extension(team, TeamTracingConfig)

    if request.method == "PATCH":
        serializer = TeamTracingConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(serializer.data)

    return response.Response(TeamTracingConfigSerializer(config).data)


def handle_experiments_config(request: request.Request, team: Team) -> response.Response:
    """Shared handler for the experiments_config action — exposed under both the
    team/environment and project routers so both surfaces stay in parity."""
    # Keeps the products app import off this module's import path.
    from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig  # noqa: PLC0415

    class TeamExperimentsConfigSerializer(serializers.ModelSerializer):
        class Meta:
            model = TeamExperimentsConfig
            fields = [
                "experiment_recalculation_time",
                "default_experiment_confidence_level",
                "default_experiment_stats_method",
                "experiment_precomputation_enabled",
                "default_only_count_matured_users",
                "default_cuped_enabled",
                "default_cuped_lookback_days",
                "default_minimum_detectable_effect",
                "default_sequential_testing_enabled",
                "default_sequential_tuning_parameter",
                "flag_cleanup_repository",
            ]

        def update(self, instance: "TeamExperimentsConfig", validated_data: dict[str, Any]) -> "TeamExperimentsConfig":
            # A human toggling precomputation must stick: the auto-enrollment job only
            # writes when precomputation_enabled_set_by is null or "auto".
            if "experiment_precomputation_enabled" in validated_data:
                instance.precomputation_enabled_set_by = TeamExperimentsConfig.PrecomputationEnabledSetBy.MANUAL
            return super().update(instance, validated_data)

        def validate_flag_cleanup_repository(self, value: str | None) -> str | None:
            # Keeps the sandbox/LLM runtime the repo-selection module pulls in off the
            # request import path.
            from products.tasks.backend.facade import repo_selection as tasks_repo_selection  # noqa: PLC0415

            if not value:
                return None
            parts = value.split("/")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise serializers.ValidationError("Repository must be in the format organization/repository")
            value = value.lower()
            # Reject repos outside the team's GitHub installation now rather than storing a
            # default the cleanup resolution would silently ignore.
            github = tasks_repo_selection.resolve_team_github_integration(team.id, team=team, team_only=True)
            cached = {
                full_name.lower()
                for repo in (github.list_all_cached_repositories(max_repos=1000) if github else [])
                if (full_name := repo.get("full_name"))
            }
            if value not in cached:
                raise serializers.ValidationError(
                    "This repository is not connected to the project's GitHub integration."
                )
            return value

    config = get_or_create_team_extension(team, TeamExperimentsConfig)

    if request.method == "PATCH":
        serializer = TeamExperimentsConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(serializer.data)

    return response.Response(TeamExperimentsConfigSerializer(config).data)


def handle_logs_config(request: request.Request, team: Team) -> response.Response:
    """Shared handler for the logs_config action — exposed under both the team/environment
    and project routers so the canonical /api/projects/ URL resolves alongside the legacy
    /api/environments/ alias. Both endpoints operate on the env-scoped TeamLogsConfig
    keyed by team_id."""
    config = get_or_create_team_extension(team, TeamLogsConfig)

    if request.method == "PATCH":
        serializer = TeamLogsConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(serializer.data)

    return response.Response(TeamLogsConfigSerializer(config).data)


def handle_evaluation_context_suggestions(request: request.Request, team: Team) -> response.Response:
    """Handler for the evaluation_context_suggestions action on the team/environment router.

    Unlike the other handlers here, this one is not shared: the project router calls its own
    `team_evaluation_context_suggestions_view`, so a change here does not reach /api/projects/.
    The import note at the top of `posthog/api/project.py` says why that copy stays local.

    Hide an evaluation context name from the flag editor's suggestion list, or restore it.
    POST hides the name; DELETE restores it. The underlying context row and any flags already
    using it are never modified — this only controls what gets suggested."""
    # Contexts are persisted under the project root team (see default_evaluation_contexts).
    root_team = team.parent_team or team

    context_name = request.data.get("context_name", "") or request.GET.get("context_name", "")
    if not isinstance(context_name, str):
        return response.Response({"error": "context_name must be a string"}, status=400)
    context_name = normalize_context_name(context_name)
    if not context_name:
        return response.Response({"error": "context_name is required"}, status=400)

    hidden = request.method == "POST"

    with transaction.atomic():
        try:
            ctx = EvaluationContext.objects.select_for_update().get(name=context_name, team=root_team)
        except EvaluationContext.DoesNotExist:
            return response.Response({"error": "Evaluation context not found"}, status=404)

        if ctx.hidden_from_suggestions != hidden:
            ctx.hidden_from_suggestions = hidden
            ctx.save(update_fields=["hidden_from_suggestions"])
            report_user_action(
                cast(User, request.user),
                "evaluation context suggestion hidden" if hidden else "evaluation context suggestion restored",
                {"team_id": team.id, "context_name": context_name},
                team=team,
                request=request,
            )

    return response.Response({"success": True, "name": context_name, "hidden_from_suggestions": hidden})


def validate_secret_token_generation(team: Team, user: User) -> None:
    """Rotating an existing legacy secret token stays allowed for safe migration, but minting a
    first one is blocked once the team has access to project secret API keys."""
    if team.secret_api_token or team.secret_api_token_backup:
        return
    if team.conversations_enabled:
        # Support signs widget identity hashes with the raw token and authenticates its external
        # API against it. Project secret API keys are only ever stored hashed, so they cannot
        # replace it, which would leave Support with no way to verify identity at all.
        return
    if posthoganalytics.feature_enabled(
        "project-secret-api-keys",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    ):
        raise exceptions.ValidationError(
            "The feature flags secure API key is deprecated. Create a project secret API key with the "
            "feature_flag:read scope instead."
        )
