# Created manually

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("posthog", "0526_remoteconfig")]

    operations = [
        migrations.RunSQL(
            """
            UPDATE posthog_project AS proj
            SET name = team.name
            FROM posthog_team AS team
            WHERE proj.id = team.project_id AND proj.name != team.name""",
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
    ]
