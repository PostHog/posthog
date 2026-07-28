from parameterized import parameterized

from products.conversations.backend.services.email_delivery import MAX_EMAIL_LENGTH, customer_email_from_traits


class TestCustomerEmailFromTraits:
    @parameterized.expand(
        [
            ("plain_address", {"email": "customer@example.com"}, "customer@example.com"),
            ("surrounding_whitespace", {"email": " customer@example.com "}, "customer@example.com"),
            ("no_email_trait", {"name": "Customer"}, None),
            ("empty_string", {"email": "   "}, None),
            ("not_an_address", {"email": "customer at example dot com"}, None),
            ("header_injection", {"email": "customer@example.com\nBcc: victim@example.com"}, None),
            ("non_string", {"email": {"address": "customer@example.com"}}, None),
            ("no_traits", None, None),
            ("over_max_length", {"email": f"{'a' * MAX_EMAIL_LENGTH}@example.com"}, None),
        ]
    )
    def test_only_usable_addresses_are_returned(self, _name, traits, expected):
        assert customer_email_from_traits(traits) == expected
