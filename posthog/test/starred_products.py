from unittest import TestCase
from unittest.mock import patch

from posthog.models.file_system.file_system_shortcut import FileSystemShortcut


def start_without_default_starred_products(test_case: TestCase) -> None:
    """Remove the default product stars users get when they join, and stop users created later from getting them.

    For tests about the shortcuts a user creates, where the defaults would only add rows to every assertion.
    """
    FileSystemShortcut.objects.all().delete()
    patcher = patch("posthog.models.file_system.starred_products.star_default_products_for_accessible_teams")
    patcher.start()
    test_case.addCleanup(patcher.stop)
