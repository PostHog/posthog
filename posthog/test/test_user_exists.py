from unittest.mock import patch

from django.test import SimpleTestCase

import posthog.user_exists
from posthog.models.user import User
from posthog.user_exists import any_user_exists


class TestAnyUserExistsCache(SimpleTestCase):
    def setUp(self) -> None:
        posthog.user_exists._any_user_exists = False
        self.addCleanup(setattr, posthog.user_exists, "_any_user_exists", False)

    def test_caches_positive_result_and_invalidates_on_user_deletion(self) -> None:
        with patch.object(User.objects, "exists", return_value=True) as mock_exists:
            assert any_user_exists() is True
            assert any_user_exists() is True
            assert mock_exists.call_count == 1  # served from cache, no repeat query

            # Deleting a user must invalidate the cached positive so an emptied instance
            # re-checks and the /preflight redirect works again.
            posthog.user_exists._reset_any_user_exists_cache(sender=User, instance=User(id=1))

            mock_exists.return_value = False
            assert any_user_exists() is False  # re-queried after invalidation
            assert mock_exists.call_count == 2
