from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("ai_observability", "0042_aiobservabilitychecklistitemstate"),
    ]

    operations = [
        # (team, definition) is already served by the auto index on the definition FK.
        SafeRemoveIndexConcurrently(
            model_name="tracereviewscore",
            name="llma_tr_score_def_idx",
        ),
        # (team, review) is served twice over: the auto index on the review FK, and the
        # llma_tr_score_def_uniq unique index that leads with the review column.
        SafeRemoveIndexConcurrently(
            model_name="tracereviewscore",
            name="llma_tr_score_rev_idx",
        ),
        # No query does array containment on categorical_values, so nothing reads this
        # GIN index; the column is only written and read whole through the serializer.
        SafeRemoveIndexConcurrently(
            model_name="tracereviewscore",
            name="llma_tr_score_cat_gin",
        ),
    ]
