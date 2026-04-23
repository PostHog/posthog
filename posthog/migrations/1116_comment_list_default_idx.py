# Generated manually for comment list performance fix

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False  # Required for AddIndexConcurrently

    dependencies = [
        ("posthog", "1115_featureflag_filters_groups_default"),
    ]

    operations = [
        # Partial index for the default comments list path (no scope filter).
        # Matches the queryset built in CommentViewSet.safely_get_queryset when
        # `scope` is not provided: team_id filter + deleted=False + scope excluding
        # conversations_ticket, ordered by -created_at with LIMIT from cursor pagination.
        # The existing posthog_comment_convo_idx covers scope-specific queries but
        # doesn't help the negated-scope predicate.
        AddIndexConcurrently(
            model_name="comment",
            index=models.Index(
                fields=["team_id", "-created_at"],
                name="posthog_comment_list_dflt_idx",
                condition=models.Q(deleted=False) & ~models.Q(scope="conversations_ticket"),
            ),
        ),
    ]
