# Generated by Django 3.2.19 on 2023-11-09 14:53
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0362_alter_flag_and_experiment_constraints"),
    ]

    operations = [
        migrations.RunSQL(
            'ALTER TABLE "posthog_experiment" VALIDATE CONSTRAINT "posthog_experiment_feature_flag_id_dc616b89_fk_posthog_f";',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            'ALTER TABLE "posthog_experiment" VALIDATE CONSTRAINT "posthog_experiment_created_by_id_b40aea95_fk_posthog_user_id";',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            'ALTER TABLE "posthog_featureflag" VALIDATE CONSTRAINT "posthog_featureflag_created_by_id_4571fe1a_fk_posthog_user_id";',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
