from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0013_relationships"),
    ]

    operations = [
        ValidateForeignKey(model_name="accountrelationshipdefinition", name="accountrelationshipdefinition_team_id_fk"),
        ValidateForeignKey(
            model_name="accountrelationshipdefinition", name="accountrelationshipdefinition_created_by_id_fk"
        ),
        ValidateForeignKey(model_name="accountrelationship", name="accountrelationship_team_id_fk"),
        ValidateForeignKey(model_name="accountrelationship", name="accountrelationship_created_by_id_fk"),
        ValidateForeignKey(model_name="accountrelationship", name="accountrelationship_user_id_fk"),
    ]
