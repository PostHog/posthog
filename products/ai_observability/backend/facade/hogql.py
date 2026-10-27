from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DANGEROUS_NoTeamIdCheckTable,
    DateTimeDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    UUIDDatabaseField,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.parser import parse_expr

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


class ScoreDefinitionVersionsTable(PostgresTable, DANGEROUS_NoTeamIdCheckTable):
    # Versions have no team_id; their parent definition supplies tenant isolation.
    def creator_owned_object_ids(
        self, user_access_control: "UserAccessControl", team_id: int | None, candidate_ids: frozenset[str] | None
    ) -> frozenset[str]:
        from products.ai_observability.backend.models.score_definitions import (  # noqa: PLC0415 -- keeps the ORM off the schema import path
            ScoreDefinition,
        )

        if team_id is None:
            raise ValueError("system.score_definition_versions requires a team")
        definitions = ScoreDefinition.objects.filter(team_id=team_id, created_by_id=user_access_control.user.pk)
        if candidate_ids is not None:
            definitions = definitions.filter(id__in=candidate_ids)
        return frozenset(str(id) for id in definitions.values_list("id", flat=True))


score_definition_versions = ScoreDefinitionVersionsTable(
    name="score_definition_versions",
    postgres_table_name="llm_analytics_scoredefinitionversion",
    access_scope="llm_analytics",
    access_control_id_field="definition_id",
    predicates=[parse_expr("definition_id IN (SELECT id FROM system.score_definitions)")],
    description="Immutable scorer configurations; one row per version of a score definition.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Scorer version UUID."),
        "definition_id": UUIDDatabaseField(
            name="definition_id", description="Parent scorer; joins to score_definitions.id."
        ),
        "version": IntegerDatabaseField(name="version", description="Version number within the scorer."),
        "config": StringJSONDatabaseField(
            name="config", description="JSON scoring configuration and passing rule for this version."
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created this version."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the version was created."),
    },
)

offline_experiments = PostgresTable(
    name="offline_experiments",
    postgres_table_name="llm_analytics_offlineexperiment",
    access_scope="evaluation",
    resource_level_access_only=True,
    description="Offline evaluation experiments; one row per submitted run.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Experiment UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Experiment name."),
        "run_source": StringDatabaseField(
            name="run_source", nullable=True, description="Where the run started: ci, local, or scheduled."
        ),
        "status": StringDatabaseField(name="status", description="Run status: uploading, completed, or failed."),
        "started_at": DateTimeDatabaseField(name="started_at", description="When the caller started the run."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When PostHog accepted the run."),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who submitted the run, when available."
        ),
        "finished_at": DateTimeDatabaseField(name="finished_at", nullable=True, description="When the run was closed."),
        "expected_item_count": IntegerDatabaseField(
            name="expected_item_count", nullable=True, description="Declared number of experiment items."
        ),
        "expected_result_count": IntegerDatabaseField(
            name="expected_result_count",
            nullable=True,
            description="Declared number of item and scorer-version results.",
        ),
        "suite_key": StringDatabaseField(
            name="suite_key", nullable=True, description="Caller-defined suite identifier for comparing runs."
        ),
        "dataset_source": StringDatabaseField(
            name="dataset_source", nullable=True, description="Source of the run's dataset."
        ),
        "dataset_identifier": StringDatabaseField(
            name="dataset_identifier", nullable=True, description="Caller-provided dataset identifier."
        ),
        "dataset_revision_identifier": StringDatabaseField(
            name="dataset_revision_identifier",
            nullable=True,
            description="Caller-provided dataset revision identifier.",
        ),
        "dataset_revision_id": UUIDDatabaseField(
            name="dataset_revision_id",
            nullable=True,
            description="Linked PostHog revision; joins to dataset_revisions.id.",
        ),
        "application_version": StringDatabaseField(
            name="application_version", nullable=True, description="Application version evaluated by this run."
        ),
        "model_version": StringDatabaseField(
            name="model_version", nullable=True, description="Default model version for items in this run."
        ),
        "prompt_version": StringDatabaseField(
            name="prompt_version", nullable=True, description="Prompt version evaluated by this run."
        ),
    },
)

offline_experiment_items = PostgresTable(
    name="offline_experiment_items",
    postgres_table_name="llm_analytics_offlineexperimentitem",
    access_scope="evaluation",
    resource_level_access_only=True,
    description="Offline experiment cases and trials; one row per submitted item.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Experiment item UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "experiment_id": UUIDDatabaseField(
            name="experiment_id", description="Parent run; joins to offline_experiments.id."
        ),
        "case_key": StringDatabaseField(name="case_key", nullable=True, description="Caller-defined case identifier."),
        "trial": StringDatabaseField(name="trial", nullable=True, description="Caller-defined trial identifier."),
        "model_version": StringDatabaseField(
            name="model_version",
            nullable=True,
            description="Item model version; NULL uses the experiment's model_version.",
        ),
        "dataset_item_identifier": StringDatabaseField(
            name="dataset_item_identifier", nullable=True, description="Caller-provided dataset item identifier."
        ),
        "dataset_item_version_identifier": StringDatabaseField(
            name="dataset_item_version_identifier",
            nullable=True,
            description="Caller-provided dataset item version identifier.",
        ),
        "dataset_item_version_id": UUIDDatabaseField(
            name="dataset_item_version_id",
            nullable=True,
            description="Linked PostHog item version; joins to dataset_item_versions.id.",
        ),
        "application_trace_id": StringDatabaseField(
            name="application_trace_id", nullable=True, description="Application trace associated with this item."
        ),
        "accepted_at": DateTimeDatabaseField(name="accepted_at", description="When PostHog accepted the item."),
        "payload_state": StringDatabaseField(
            name="payload_state", description="Payload availability: not_provided, available, or expired."
        ),
        "payload_expires_at": DateTimeDatabaseField(
            name="payload_expires_at", nullable=True, description="When the item's optional payload expires."
        ),
    },
)

offline_evaluation_results = PostgresTable(
    name="offline_evaluation_results",
    postgres_table_name="llm_analytics_offlineevaluationresult",
    access_scope="evaluation",
    resource_level_access_only=True,
    predicates=[parse_expr("scorer_version_id IN (SELECT id FROM system.score_definition_versions)")],
    description="Offline evaluation outcomes; one row per experiment item and scorer version, including unsuccessful outcomes.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Evaluation result UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "item_id": UUIDDatabaseField(
            name="item_id", description="Evaluated item; joins to offline_experiment_items.id."
        ),
        "scorer_definition_id": UUIDDatabaseField(
            name="scorer_definition_id", description="Scorer identity; joins to score_definitions.id."
        ),
        "scorer_version_id": UUIDDatabaseField(
            name="scorer_version_id", description="Pinned scorer configuration; joins to score_definition_versions.id."
        ),
        "status": StringDatabaseField(name="status", description="Outcome: ok, error, skipped, or not_applicable."),
        "numeric_value": FloatDatabaseField(
            name="numeric_value", nullable=True, description="Numeric score for a successful numeric result."
        ),
        "boolean_value": BooleanDatabaseField(
            name="boolean_value", nullable=True, description="Boolean score for a successful boolean result."
        ),
        "categorical_values": StringArrayDatabaseField(
            name="categorical_values",
            nullable=True,
            description="Selected category keys for a successful categorical result.",
        ),
        "error_code": StringDatabaseField(
            name="error_code", nullable=True, description="Caller-provided error code for an error outcome."
        ),
        "evaluator_trace_id": StringDatabaseField(
            name="evaluator_trace_id", nullable=True, description="Trace associated with the scorer execution."
        ),
        "evaluated_at": DateTimeDatabaseField(
            name="evaluated_at", nullable=True, description="When the caller evaluated the result."
        ),
        "accepted_at": DateTimeDatabaseField(name="accepted_at", description="When PostHog accepted the result."),
        "payload_state": StringDatabaseField(
            name="payload_state", description="Payload availability: not_provided, available, or expired."
        ),
        "payload_expires_at": DateTimeDatabaseField(
            name="payload_expires_at", nullable=True, description="When the result's optional payload expires."
        ),
    },
)

offline_experiment_item_payloads = PostgresTable(
    name="offline_experiment_item_payloads",
    postgres_table_name="llm_analytics_offlineexperimentitempayload",
    access_scope="evaluation",
    resource_level_access_only=True,
    predicates=[parse_expr("id IN (SELECT id FROM system.offline_experiment_items WHERE payload_state = 'available')")],
    description="Available offline item payloads containing submitted inputs, outputs, and metadata; one row per item with a payload.",
    fields={
        "id": UUIDDatabaseField(name="item_id", description="Item UUID; joins to offline_experiment_items.id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "data": StringJSONDatabaseField(name="data", description="Submitted JSON item payload."),
    },
)

offline_evaluation_result_payloads = PostgresTable(
    name="offline_evaluation_result_payloads",
    postgres_table_name="llm_analytics_offlineevaluationresultpayload",
    access_scope="evaluation",
    resource_level_access_only=True,
    predicates=[
        parse_expr("id IN (SELECT id FROM system.offline_evaluation_results WHERE payload_state = 'available')")
    ],
    description="Available offline result payloads containing scoring details; one row per result with a payload.",
    fields={
        "id": UUIDDatabaseField(name="result_id", description="Result UUID; joins to offline_evaluation_results.id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "data": StringJSONDatabaseField(name="data", description="Submitted JSON result payload."),
    },
)

offline_evaluation_usage_ledger = PostgresTable(
    name="offline_evaluation_usage_ledger",
    postgres_table_name="llm_analytics_offlineevaluationusageledger",
    access_scope="evaluation",
    resource_level_access_only=True,
    description="Append-only offline evaluation usage; each row counts newly accepted results across all statuses and survives experiment deletion.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Usage ledger entry UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "experiment_id": UUIDDatabaseField(
            name="experiment_id", description="Run UUID; joins to offline_experiments.id if the run still exists."
        ),
        "accepted_at": DateTimeDatabaseField(name="accepted_at", description="When the usage was recorded."),
        "quantity": IntegerDatabaseField(
            name="quantity", description="Number of newly accepted results in this entry, across all statuses."
        ),
    },
)
