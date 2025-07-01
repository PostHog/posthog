# Test migration with fixed workflow links
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0783_remove_segment_engage_destinations"),
    ]
    operations = []
