from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1368_sessionrecording_untrack_lts_fields"),
    ]

    operations = [
        migrations.RunSQL("SELECT 1", reverse_sql="SELECT 1"),
    ]
