from unittest import TestCase

from parameterized import parameterized
from rest_framework import serializers

from posthog.api.oauth.client_name import CLIENT_NAME_MAX_LENGTH, sanitize_client_name, validate_client_name


class TestSanitizeClientName(TestCase):
    @parameterized.expand(
        [
            ("plain_name", "My Analytics App", "My Analytics App"),
            ("script_tag", "<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
            ("ampersand_in_middle", "Tom & Jerry", "Tom &amp; Jerry"),
            ("quote", "John's App", "John&#x27;s App"),
        ]
    )
    def test_escapes_short_names_without_truncation(self, _name, value, expected):
        self.assertEqual(sanitize_client_name(value), expected)

    @parameterized.expand(
        [
            # "&" escapes to "&amp;" (5 chars). Pad so truncation slices through it, leaving a
            # dangling fragment that must be stripped entirely rather than rendered.
            ("amp_cut_to_bare_ampersand", "a" * 254 + "&", "a" * 254),
            ("amp_cut_to_partial", "a" * 252 + "&", "a" * 252),
            # "'" escapes to "&#x27;" (6 chars) — exercises the "#"/digits in the entity char class.
            ("numeric_entity_cut", "a" * 250 + "'", "a" * 250),
            # A complete entity sitting exactly on the boundary must be preserved, not over-stripped.
            ("complete_entity_preserved_at_boundary", "a" * 250 + "&", "a" * 250 + "&amp;"),
            # No special chars: plain truncation with nothing to strip.
            ("plain_truncation", "a" * 300, "a" * 255),
        ]
    )
    def test_strips_dangling_entity_after_truncation(self, _name, value, expected):
        result = sanitize_client_name(value)

        self.assertEqual(result, expected)
        self.assertLessEqual(len(result), CLIENT_NAME_MAX_LENGTH)


class TestValidateClientName(TestCase):
    @parameterized.expand(
        [
            ("prefix_posthog", "PostHog Client"),
            ("prefix_posthog_lowercase", "posthog-integration"),
            ("word_official", "Official MCP Client"),
            ("word_verified", "My Verified App"),
            ("word_trusted_embedded", "MYTRUSTEDAPP"),
        ]
    )
    def test_rejects_impersonating_names(self, _name, value):
        with self.assertRaises(serializers.ValidationError):
            validate_client_name(value)

    @parameterized.expand(
        [
            ("contains_but_not_prefixed_by_posthog", "Claude Code (posthog-local)"),
            ("unrelated_name", "My Analytics Dashboard"),
        ]
    )
    def test_accepts_valid_names(self, _name, value):
        validate_client_name(value)
