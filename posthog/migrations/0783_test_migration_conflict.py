# Test migration file to trigger conflict detection workflow
# This is a temporary file for testing the new comment-based resolution system

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0782_previous_migration'),  # This will create a simulated conflict
    ]

    operations = [
        # Empty migration for testing purposes
    ]
