import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("annotations", "0003_annotation_hidden_in_user_interface"),
        ("posthog", "1247_oauthaccesstoken_token_idx"),
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
                    name="annotation",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tagged_items",
                        to="annotations.annotation",
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
                            "annotation",
                        )
                    },
                ),
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("annotation__isnull", False)),
                        fields=("tag", "annotation"),
                        name="unique_annotation_tagged_item",
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", True),
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
                                ("annotation__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="exactly_one_related_object",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_taggeditem"
                        ADD COLUMN "annotation_id" integer NULL
                        CONSTRAINT "posthog_taggeditem_annotation_id_fk"
                        REFERENCES "posthog_annotation"("id")
                        DEFERRABLE INITIALLY DEFERRED; -- existing-table-constraint-ignore
                        SET CONSTRAINTS "posthog_taggeditem_annotation_id_fk" IMMEDIATE; -- existing-table-constraint-ignore
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_taggeditem" DROP COLUMN IF EXISTS "annotation_id";
                    """,
                ),
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "exactly_one_related_object";
                        ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "exactly_one_related_object" CHECK ( /* -- existing-table-constraint-ignore */
                            (
                                (dashboard_id IS NOT NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NOT NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NOT NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NOT NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NOT NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NOT NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NOT NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NOT NULL AND account_id IS NULL AND endpoint_id IS NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NOT NULL AND endpoint_id IS NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NOT NULL AND annotation_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL AND annotation_id IS NOT NULL) /* -- not-null-ignore */
                            )
                        ) NOT VALID;
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "exactly_one_related_object";
                        ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "exactly_one_related_object" CHECK ( /* -- existing-table-constraint-ignore */
                            (
                                (dashboard_id IS NOT NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NOT NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NOT NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NOT NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NOT NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NOT NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NOT NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NOT NULL AND account_id IS NULL AND endpoint_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NOT NULL AND endpoint_id IS NULL) OR /* -- not-null-ignore */
                                (dashboard_id IS NULL AND insight_id IS NULL AND event_definition_id IS NULL AND property_definition_id IS NULL AND action_id IS NULL AND feature_flag_id IS NULL AND experiment_saved_metric_id IS NULL AND ticket_id IS NULL AND account_id IS NULL AND endpoint_id IS NOT NULL) /* -- not-null-ignore */
                            )
                        ) NOT VALID;
                    """,
                ),
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_endpoint_uniq";
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        )
    ]
