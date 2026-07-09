from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0011_bk_doc_embed_state_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgesource",
            name="always_include",
            field=models.BooleanField(default=False),
        ),
    ]
