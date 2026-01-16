# Generated migration for conversation forking

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0037_add_conversation_approval_decisions"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="forked_from",
            field=models.ForeignKey(
                blank=True,
                help_text="The conversation this was forked from, if any. Used when continuing a shared conversation.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="forks",
                to="ee.conversation",
            ),
        ),
        migrations.AddField(
            model_name="conversation",
            name="forked_at_message_index",
            field=models.IntegerField(
                blank=True,
                help_text="The index of the last message from the original conversation when forked. Messages after this index are only visible to the fork owner.",
                null=True,
            ),
        ),
    ]
