from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    """Drop the table 0089 took out of Django state.

    0089 removed Tagger from state and dropped the table's foreign keys, and kept the table so
    pods on the old release could still read it through a rolling deploy. Nothing reads it now.
    """

    dependencies = [
        ("ai_observability", "0092_trace_review_project_key_attribution"),
    ]

    operations = [
        SafeDropTable("llm_analytics_tagger"),
    ]
