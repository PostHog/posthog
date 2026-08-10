from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("posthog", "1299_taggeditem_notebook_indexes")]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "posthog_taggeditem_tag_id_dashboard_id_insi_notebook_uniq"
                UNIQUE USING INDEX "posthog_taggeditem_tag_id_dashboard_id_insi_notebook_uniq"; -- existing-table-constraint-ignore
            """,
            reverse_sql="""
                ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_notebook_uniq";
            """,
        ),
    ]
