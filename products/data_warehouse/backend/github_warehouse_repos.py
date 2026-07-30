"""Reconcile a GitHub warehouse source after its repository list changes.

A GitHub source syncs N repos through one set of `ExternalDataSchema` rows per repo × endpoint
(the legacy pre-multi-repo repo keeps bare endpoint names; every other repo is qualified as
`owner/repo.endpoint`) and one webhook HogFunction whose `schema_mapping` routes incoming events
per repo. When a PATCH changes `job_inputs.repositories`, this module:

- creates schema rows for added repos (strict name matching, so a qualified `owner/repo.issues`
  never collapses onto the legacy bare `issues` row) with their location metadata seeded,
- disables/soft-deletes removed repos' rows via the standard discovery-removal policy,
- creates hooks in added repos (pinned to the source's existing signing secret), deletes hooks
  from removed repos, and rewrites `schema_mapping` from scratch so removed repos are pruned.

Webhook failures never fail the PATCH — job_inputs are already persisted, the 6h schema-discovery
activity self-heals missing rows, and hook drift is surfaced by the webhook status endpoint.
"""

from typing import Any, cast

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.data_warehouse.backend.logic.external_data_source.webhooks import get_webhook_url
from products.warehouse_sources.backend.facade.models import (
    ExternalDataSchema,
    ExternalDataSource,
    sync_old_schemas_with_new_schemas,
)
from products.warehouse_sources.backend.facade.source_management import GithubSource, SourceRegistry
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


def github_repositories_for_job_inputs(job_inputs: dict[str, Any] | None) -> list[str]:
    """The effective repo list for stored GitHub job_inputs; [] when unparseable or unset."""
    source = cast(GithubSource, SourceRegistry.get_source(ExternalDataSourceType.GITHUB))
    try:
        return GithubSource.effective_repositories(source.parse_config(job_inputs or {}))
    except Exception:
        return []


def reconcile_github_repositories(
    *,
    source_model: ExternalDataSource,
    team: Team,
    old_repositories: list[str],
    new_config: Any,
) -> None:
    """Bring schema rows and repo webhooks in line with the (already persisted) new repo list."""
    source = cast(GithubSource, SourceRegistry.get_source(ExternalDataSourceType.GITHUB))
    try:
        new_repositories = GithubSource.effective_repositories(new_config)
    except ValueError:
        new_repositories = []
    if new_repositories == old_repositories:
        return

    source_schemas = source.get_schemas(new_config, team.pk)
    sync_old_schemas_with_new_schemas(
        {schema.name: schema.label for schema in source_schemas},
        source_id=str(source_model.id),
        team_id=team.pk,
        strict_name_match=True,
        schema_metadata_by_name={
            schema.name: schema.schema_metadata for schema in source_schemas if schema.schema_metadata
        },
    )

    try:
        _reconcile_repo_webhooks(
            source=source,
            source_model=source_model,
            team=team,
            new_config=new_config,
            source_schemas=source_schemas,
            added=[repo for repo in new_repositories if repo not in old_repositories],
            removed=[repo for repo in old_repositories if repo not in new_repositories],
        )
    except Exception as e:
        # Hook drift is recoverable (webhook status endpoint + idempotent re-create); a failed
        # PATCH after job_inputs persisted is not.
        capture_exception(e, {"source_id": str(source_model.id), "team_id": team.pk})
        logger.exception("github_repo_webhook_reconcile_failed", source_id=str(source_model.id), error=str(e))


def _reconcile_repo_webhooks(
    *,
    source: GithubSource,
    source_model: ExternalDataSource,
    team: Team,
    new_config: Any,
    source_schemas: list[Any],
    added: list[str],
    removed: list[str],
) -> None:
    hog_function = HogFunction.objects.filter(
        team=team,
        type="warehouse_source_webhook",
        inputs__source_id__value=str(source_model.id),
        deleted=False,
    ).first()
    if hog_function is None:
        # No webhook set up for this source — nothing to create hooks against. Rows for added
        # repos stay poll-based until the user sets the webhook up, which covers every repo.
        return

    webhook_url = get_webhook_url(str(hog_function.id))
    signing_secret = ((hog_function.encrypted_inputs or {}).get("signing_secret") or {}).get("value")

    failures: list[str] = []
    if added:
        if signing_secret:
            failures.extend(
                source.ensure_webhooks_for_repositories(new_config, webhook_url, team.pk, added, signing_secret)
            )
        else:
            failures.append(
                "no signing secret is stored for this source's webhook; re-create the webhook to cover the added repositories"
            )
    if removed:
        failures.extend(source.delete_webhooks_for_repositories(new_config, webhook_url, team.pk, removed))
    if failures:
        logger.warning(
            "github_repo_webhook_reconcile_partial",
            source_id=str(source_model.id),
            failures=failures,
        )

    # Rewrite the mapping from scratch (not merge) so removed repos' keys are pruned. Newly added
    # repos' webhook-capable rows are created disabled and join the mapping when the user enables
    # them through the schema update path.
    webhook_capable = {schema.name for schema in source_schemas if schema.supports_webhooks}
    eligible_schemas = ExternalDataSchema.objects.filter(
        source_id=source_model.id,
        team_id=team.pk,
        sync_type=ExternalDataSchema.SyncType.WEBHOOK,
        should_sync=True,
        name__in=webhook_capable,
    ).exclude(deleted=True)
    schema_mapping = {source.webhook_mapping_key(schema.name): str(schema.id) for schema in eligible_schemas}
    # Re-pin the legacy repository alongside the mapping so the template's bare-key fallback stays
    # bound to it — a mixed legacy+multi-repo source is exactly the case the fallback could leak.
    hog_function.inputs = {
        **(hog_function.inputs or {}),
        "schema_mapping": {"value": schema_mapping},
        **{key: {"value": value} for key, value in source.webhook_template_inputs(new_config).items()},
    }
    hog_function.save(update_fields=["inputs", "encrypted_inputs"])
