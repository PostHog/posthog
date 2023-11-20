# Generated by Django 3.2.19 on 2023-11-09 10:35

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0364_team_external_data_workspace_rows"),
    ]

    # :TRICKY:
    # We are replacing the original generated migration:
    # migrations.AlterField(
    #     model_name='experiment',
    #     name='created_by',
    #     field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
    # ),
    # migrations.AlterField(
    #     model_name='featureflag',
    #     name='created_by',
    #     field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
    # ),
    # with one that adds the 'NOT VALID' directive, which applies the constraint only for inserts/updates.
    # This ensures the table is not locked when creating the new constraint.
    # A follow up migration will validate the constraint.
    # The code here is exactly the same as the one generated by the default migration, except for the 'NOT VALID' directive.

    operations = [
        # make the created_by column nullable in experiments & flags
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="experiment",
                    name="created_by",
                    field=models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
                migrations.AlterField(
                    model_name="featureflag",
                    name="created_by",
                    field=models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    """
                    SET CONSTRAINTS "posthog_experiment_created_by_id_b40aea95_fk_posthog_user_id" IMMEDIATE;
                    ALTER TABLE "posthog_experiment" DROP CONSTRAINT "posthog_experiment_created_by_id_b40aea95_fk_posthog_user_id";
                    ALTER TABLE "posthog_experiment" ALTER COLUMN "created_by_id" DROP NOT NULL;
                    ALTER TABLE "posthog_experiment" ADD CONSTRAINT "posthog_experiment_created_by_id_b40aea95_fk_posthog_user_id" FOREIGN KEY ("created_by_id") REFERENCES "posthog_user" ("id") DEFERRABLE INITIALLY DEFERRED NOT VALID;
                    """,
                    reverse_sql="""
                        SET CONSTRAINTS "posthog_experiment_created_by_id_b40aea95_fk_posthog_user_id" IMMEDIATE;
                        ALTER TABLE "posthog_experiment" DROP CONSTRAINT "posthog_experiment_created_by_id_b40aea95_fk_posthog_user_id";
                        ALTER TABLE "posthog_experiment" ALTER COLUMN "created_by_id" SET NOT NULL;
                        ALTER TABLE "posthog_experiment" ADD CONSTRAINT "posthog_experiment_created_by_id_b40aea95_fk_posthog_user_id" FOREIGN KEY ("created_by_id") REFERENCES "posthog_user" ("id") DEFERRABLE INITIALLY DEFERRED NOT VALID;
                    """,
                ),
                migrations.RunSQL(
                    """SET CONSTRAINTS "posthog_featureflag_created_by_id_4571fe1a_fk_posthog_user_id" IMMEDIATE;
                    ALTER TABLE "posthog_featureflag" DROP CONSTRAINT "posthog_featureflag_created_by_id_4571fe1a_fk_posthog_user_id";
                    ALTER TABLE "posthog_featureflag" ALTER COLUMN "created_by_id" DROP NOT NULL;
                    ALTER TABLE "posthog_featureflag" ADD CONSTRAINT "posthog_featureflag_created_by_id_4571fe1a_fk_posthog_user_id" FOREIGN KEY ("created_by_id") REFERENCES "posthog_user" ("id") DEFERRABLE INITIALLY DEFERRED NOT VALID;
                    """,
                    reverse_sql="""
                        SET CONSTRAINTS "posthog_featureflag_created_by_id_4571fe1a_fk_posthog_user_id" IMMEDIATE;
                        ALTER TABLE "posthog_featureflag" DROP CONSTRAINT "posthog_featureflag_created_by_id_4571fe1a_fk_posthog_user_id";
                        ALTER TABLE "posthog_featureflag" ALTER COLUMN "created_by_id" SET NOT NULL;
                        ALTER TABLE "posthog_featureflag" ADD CONSTRAINT "posthog_featureflag_created_by_id_4571fe1a_fk_posthog_user_id" FOREIGN KEY ("created_by_id") REFERENCES "posthog_user" ("id") DEFERRABLE INITIALLY DEFERRED NOT VALID;
                    """,
                ),
            ],
        ),
    ]
