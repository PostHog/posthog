from django.db import migrations

from posthog.migration_helpers.concurrent_index import DropIndexConcurrently


class Migration(migrations.Migration):
    # DROP INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1331_messagingrecord_campaign_key_idx"),
    ]

    operations = [
        # The `multi_tenancy` app was layered on top of this open-source app by the
        # private posthog-cloud repo and deprecated in June 2023. Its tables are not
        # Django models here, so there is no model or state to change - only orphaned
        # objects in Cloud Postgres. `OrganizationBilling.plan` created this foreign-key
        # index, which has had no reader since the deprecation, so pganalyze keeps
        # flagging it as unused. Drop it. `IF EXISTS` makes this a no-op on every
        # database that never had the `multi_tenancy` app (open-source installs, CI, dev).
        #
        # `recreate_on_reverse=False` makes the rollback a no-op. This index maps to
        # no Django model, so a reverse CREATE would target a table that is absent
        # here (CI, dev, open-source) and fail with UndefinedTable. A rollback must
        # not resurrect the dead index either. The migration stays reversible, so
        # backward-migrating tests (TestMigrations) can unapply past it.
        DropIndexConcurrently(
            index_name="multi_tenancy_organizationbilling_plan_id_0a111163",
            table_name="multi_tenancy_organizationbilling",
            columns="(plan_id)",
            recreate_on_reverse=False,
        ),
    ]
