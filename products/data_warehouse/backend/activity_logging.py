import dataclasses

from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.activity_logging.external_data_utils import (
    get_external_data_source_created_by_info,
    get_external_data_source_detail_name,
)
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.warehouse_sources.backend.facade.models import (
    ExternalDataSchema,
    ExternalDataSource,
    sync_frequency_interval_to_sync_frequency,
)

# Lives here, not in the api/external_data_{schema,source}.py viewsets, so these can wire at
# AppConfig.ready() without dragging those viewsets (which pull dlt via the data-import pipeline
# imports) onto the django.setup() path. The Temporal data-import workflows mutate these models, so
# the audit log must connect there too.


@dataclasses.dataclass(frozen=True)
class ExternalDataSchemaContext(ActivityContextBase):
    name: str
    sync_type: str | None
    sync_frequency: str | None
    source_id: str
    source_type: str


@mutable_receiver(model_activity_signal, sender=ExternalDataSchema)
def handle_external_data_schema_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    if activity == "created":
        # We don't want to log the creation of schemas as they get bulk created on source creation
        return

    external_data_schema = after_update or before_update

    if not external_data_schema:
        return

    source = external_data_schema.source
    source_type = source.source_type if source else ""

    sync_frequency = None
    if external_data_schema.sync_frequency_interval:
        sync_frequency = sync_frequency_interval_to_sync_frequency(external_data_schema.sync_frequency_interval)

    context = ExternalDataSchemaContext(
        name=external_data_schema.name or "",
        sync_type=external_data_schema.sync_type,
        sync_frequency=sync_frequency,
        source_id=str(source.id) if source else "",
        source_type=source_type,
    )

    log_activity(
        organization_id=external_data_schema.team.organization_id,
        team_id=external_data_schema.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=external_data_schema.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=external_data_schema.name,
            context=context,
        ),
    )


@dataclasses.dataclass(frozen=True)
class ExternalDataSourceContext(ActivityContextBase):
    source_type: str
    prefix: str | None
    description: str | None
    created_by_user_id: str | None
    created_by_user_email: str | None
    created_by_user_name: str | None


@mutable_receiver(model_activity_signal, sender=ExternalDataSource)
def handle_external_data_source_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # Use after_update for create/update, before_update for delete
    external_data_source = after_update or before_update

    if not external_data_source:
        return

    created_by_user_id, created_by_user_email, created_by_user_name = get_external_data_source_created_by_info(
        external_data_source
    )
    detail_name = get_external_data_source_detail_name(external_data_source)

    context = ExternalDataSourceContext(
        source_type=external_data_source.source_type or "",
        prefix=external_data_source.prefix,
        description=external_data_source.description,
        created_by_user_id=created_by_user_id,
        created_by_user_email=created_by_user_email,
        created_by_user_name=created_by_user_name,
    )

    log_activity(
        organization_id=external_data_source.team.organization_id,
        team_id=external_data_source.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=external_data_source.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )
