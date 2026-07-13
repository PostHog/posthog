from posthog.test.base import BaseTest

from posthog.migration_helpers import chunked_queryset_iterator
from posthog.models import Comment

SCOPE = "test-chunked-iterator"


class TestChunkedQuerysetIterator(BaseTest):
    def test_yields_every_row_exactly_once_across_chunk_boundaries(self):
        created = {Comment.objects.create(team=self.team, scope=SCOPE, content=f"c{i}").pk for i in range(25)}

        seen = [
            c.pk for c in chunked_queryset_iterator(Comment.objects.filter(team=self.team, scope=SCOPE), chunk_size=10)
        ]

        assert len(seen) == 25
        assert set(seen) == created

    def test_no_skip_or_repeat_when_rows_are_updated_out_of_the_filter_mid_iteration(self):
        # The bulk_update-while-iterating pattern these migrations use: a row updated so it
        # no longer matches the filter must not be skipped or revisited. Keyset pagination
        # guarantees this; an OFFSET-based reimplementation would skip half the rows.
        for _ in range(30):
            Comment.objects.create(team=self.team, scope=SCOPE, content="pending")

        processed = []
        for comment in chunked_queryset_iterator(
            Comment.objects.filter(team=self.team, scope=SCOPE, content="pending"), chunk_size=10
        ):
            processed.append(comment.pk)
            comment.content = "done"
            comment.save(update_fields=["content"])

        assert len(processed) == 30
        assert len(set(processed)) == 30
        assert Comment.objects.filter(team=self.team, scope=SCOPE, content="pending").count() == 0
