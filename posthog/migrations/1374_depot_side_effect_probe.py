from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1373_taggeditem_generic_pointer_unique"),
    ]

    operations = [
        migrations.RunSQL("SELECT 1", reverse_sql="SELECT 1"),
    ]
