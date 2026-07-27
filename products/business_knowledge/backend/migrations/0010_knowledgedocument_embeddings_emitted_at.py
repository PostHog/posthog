# Adds a nullable timestamp marking when a document's chunks were last produced
# to the embedding pipeline. Additive + nullable — a brief metadata lock, safe
# online. The backing partial index is built CONCURRENTLY in 0011.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0009_bk_chunk_content_tsv_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgedocument",
            name="embeddings_emitted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
