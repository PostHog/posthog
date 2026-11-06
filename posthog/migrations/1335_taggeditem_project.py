import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1334_remove_cimd_blocklist_entry"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="taggeditem",
                    name="exactly_one_related_object",
                ),
                migrations.AlterUniqueTogether(
                    name="taggeditem",
                    unique_together=set(),
                ),
                migrations.AddField(
                    model_name="taggeditem",
                    name="project",
                    field=models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tagged_items",
                        to="posthog.project",
                    ),
                ),
                migrations.AlterUniqueTogether(
                    name="taggeditem",
                    unique_together={
                        (
                            "tag",
                            "dashboard",
                            "insight",
                            "event_definition",
                            "property_definition",
                            "action",
                            "feature_flag",
                            "experiment_saved_metric",
                            "ticket",
                            "account",
                            "endpoint",
                            "replay_scanner",
                            "project",
                        )
                    },
                ),
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("project__isnull", False)),
                        fields=("tag", "project"),
                        name="unique_project_tagged_item",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("dashboard__isnull", False),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", False),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", False),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", False),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", False),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", False),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", False),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", False),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", False),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", False),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", False),
                                ("project__isnull", True),
                            ),
                            models.Q(
                                ("dashboard__isnull", True),
                                ("insight__isnull", True),
                                ("event_definition__isnull", True),
                                ("property_definition__isnull", True),
                                ("action__isnull", True),
                                ("feature_flag__isnull", True),
                                ("experiment_saved_metric__isnull", True),
                                ("ticket__isnull", True),
                                ("account__isnull", True),
                                ("endpoint__isnull", True),
                                ("replay_scanner__isnull", True),
                                ("project__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="exactly_one_related_object",
                    ),
                ),
            ],
            database_operations=[
                # posthog_project is read on nearly every request, so the column lands without
                # an inline FK constraint. 1338 adds the constraint NOT VALID and 1339 validates
                # it, which keeps the lock on the parent to a brief metadata-only ALTER.
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_taggeditem" ADD COLUMN "project_id" bigint NULL;
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_taggeditem" DROP COLUMN IF EXISTS "project_id";
                    """,
                ),
                migrations.RunSQL(
                    sql="""
                                ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "exactly_one_related_object";
                                ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "exactly_one_related_object" CHECK ( /* -- existing-table-constraint-ignore */
                                    (
                                    (dashboard_id IS NOT NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NOT NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NOT NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NOT NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NOT NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NOT NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NOT NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NOT NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NOT NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NOT NULL AND replay_scanner_id IS NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NOT NULL AND project_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NOT NULL) /* -- not-null-ignore */
                                    )
                                ) NOT VALID;
                    """,
                    reverse_sql="""
                                ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "exactly_one_related_object";
                                ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "exactly_one_related_object" CHECK ( /* -- existing-table-constraint-ignore */
                                    (
                                    (dashboard_id IS NOT NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NOT NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NOT NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NOT NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NOT NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NOT NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NOT NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NOT NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NOT NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NOT NULL AND replay_scanner_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NOT NULL) /* -- not-null-ignore */
                                    )
                                ) NOT VALID;
                    """,
                ),
                # 1337 re-adds this as a constraint over the index 1336 builds concurrently.
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_replay_scan_uniq";
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
