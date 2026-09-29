import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0058_accountrelationshipdefinition_claim_saved_query_sha256"),
    ]

    # State only: the models keep their pre-rename table, column, index and constraint names,
    # so old and new code read the same schema during the deploy.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(model_name="announcementdelivery", name="ca_ann_deliv_status_idx"),
                migrations.RemoveConstraint(model_name="announcementdelivery", name="ca_announcement_delivery_uniq"),
                migrations.RenameModel(old_name="Announcement", new_name="Shoutout"),
                migrations.RenameModel(old_name="AnnouncementDelivery", new_name="ShoutoutDelivery"),
                migrations.AlterModelTable(name="shoutout", table="customer_analytics_announcement"),
                migrations.AlterModelTable(name="shoutoutdelivery", table="customer_analytics_announcementdelivery"),
                migrations.RenameField(model_name="shoutoutdelivery", old_name="announcement", new_name="shoutout"),
                migrations.AlterField(
                    model_name="shoutoutdelivery",
                    name="shoutout",
                    field=models.ForeignKey(
                        db_column="announcement_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="customer_analytics.shoutout",
                    ),
                ),
                migrations.AddIndex(
                    model_name="shoutoutdelivery",
                    index=models.Index(fields=["shoutout_id", "status"], name="ca_ann_deliv_status_idx"),
                ),
                migrations.AddConstraint(
                    model_name="shoutoutdelivery",
                    constraint=models.UniqueConstraint(
                        fields=("shoutout", "slack_channel_id"), name="ca_announcement_delivery_uniq"
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
