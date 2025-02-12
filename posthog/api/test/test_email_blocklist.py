from posthog.models.user import is_on_blocklist
from parameterized import parameterized

from django.test import SimpleTestCase


class EmailBlockListMatchingTests(SimpleTestCase):
    @parameterized.expand(
        [
            ("can_handle_no_blocklist_being_set", None, "email@email.io", False),
            ("can_handle_not_being_on_blocklist", ["email.io"], "paul@posthog.com", False),
            ("can_handle_being_on_blocklist", ["email.io"], "paul@email.io", True),
            ("can_handle_parent_domain_being_on_blocklist", ["email.io"], "paul@sub.email.io", True),
            ("can_handle_similar_domain_being_on_blocklist", ["email.io"], "paul@notemail.io", False),
            ("can_handle_subdomain_explicitly_on_blocklist", ["sub.email.io"], "paul@sub.email.io", True),
            ("can_handle_case_insensitive_blocklist", ["Email.IO"], "email@email.io", True),
            ("can_handle_case_insensitive_subdomain", ["Email.IO"], "email@sub.email.io", True),
            ("can_handle_non_matching_similar_domain", ["email.io"], "email@fake-email.io", False),
            ("can_handle_invalid_email_format", ["email.io"], "invalid-email", False),
            ("can_handle_empty_email", ["email.io"], "", False),
        ]
    )
    def test_is_on_blocklist(self, _name, blocklist, email, expected):
        with self.settings(EMAIL_DOMAIN_BLOCKLIST=blocklist):
            assert is_on_blocklist(email) is expected
