import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        # Only the new relation's target needs pinning (matching the project precedent in 1335);
        # the other TaggedItem FK columns already exist in state via their own earlier migrations.
        ("experiments", "0029_experiment_repository"),
        ("posthog", "1345_squash_2026_09_07_schema_addons"),
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
                    name="experiment",
                    field=models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tagged_items",
                        to="experiments.experiment",
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
                            "experiment",
                        )
                    },
                ),
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("experiment__isnull", False)),
                        fields=("tag", "experiment"),
                        name="unique_experiment_tagged_item",
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("experiment__isnull", True),
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
                                ("project__isnull", True),
                                ("experiment__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="exactly_one_related_object",
                    ),
                ),
            ],
            database_operations=[
                # posthog_experiment backs the whole experiments product, so the column lands
                # without an inline FK constraint. 1349 adds the constraint NOT VALID and 1350
                # validates it, which keeps the lock on the parent to a brief metadata-only ALTER.
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_taggeditem" ADD COLUMN "experiment_id" integer NULL;
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_taggeditem" DROP COLUMN IF EXISTS "experiment_id";
                    """,
                ),
                migrations.RunSQL(
                    sql="""
                                ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "exactly_one_related_object";
                                ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "exactly_one_related_object" CHECK ( /* -- existing-table-constraint-ignore */
                                    (
                                    (dashboard_id IS NOT NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NOT NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NOT NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NOT NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NOT NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NOT NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NOT NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NOT NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NOT NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NOT NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NOT NULL AND project_id IS NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NOT NULL AND experiment_id IS NULL) OR /* -- not-null-ignore */
                                    (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND replay_scanner_id IS NULL AND project_id IS NULL AND experiment_id IS NOT NULL) /* -- not-null-ignore */
                                    )
                                ) NOT VALID;
                    """,
                    reverse_sql="""
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
                ),
                # 1348 re-adds this as a constraint over the index 1347 builds concurrently.
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_4ec15a8f_uniq";
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
