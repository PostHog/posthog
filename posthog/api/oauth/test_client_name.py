from unittest import TestCase

from parameterized import parameterized
from rest_framework import serializers

from posthog.api.oauth.client_name import (
    CLIENT_NAME_MAX_LENGTH,
    is_posthog_owned_host,
    sanitize_client_name,
    validate_cimd_client_name,
    validate_client_name,
)


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


class TestValidateCimdClientName(TestCase):
    @parameterized.expand(
        [
            ("prefix", "PostHog Client"),
            ("suffix", "Claude for PostHog"),
            ("middle_lowercase", "acme posthog sync"),
            ("split_by_space", "Acme Post Hog"),
            ("split_by_punctuation", "Acme Post-Hog"),
            ("blocked_word", "Acme Trusted Client"),
        ]
    )
    def test_rejects_on_other_domains(self, _name, value):
        with self.assertRaises(serializers.ValidationError):
            validate_cimd_client_name(value, "app.example.com")

    @parameterized.expand(
        [
            ("apex", "posthog.com"),
            ("subdomain", "artifacts.posthog.com"),
            ("net", "posthog.net"),
            ("dev", "x.posthog.dev"),
        ]
    )
    def test_allows_posthog_on_posthog_owned_domains(self, _name, host):
        validate_cimd_client_name("PostHog Artifacts", host)

    def test_blocked_words_apply_on_posthog_owned_domains(self):
        with self.assertRaises(serializers.ValidationError):
            validate_cimd_client_name("PostHog Official", "posthog.com")

    def test_accepts_unrelated_name(self):
        validate_cimd_client_name("Acme Analytics", "app.example.com")


class TestIsPosthogOwnedHost(TestCase):
    @parameterized.expand(
        [
            ("apex", "posthog.com", True),
            ("subdomain", "artifacts.posthog.com", True),
            ("uppercase_and_trailing_dot", "Artifacts.PostHog.com.", True),
            ("net", "posthog.net", True),
            ("dev", "posthog.dev", True),
            ("lookalike", "evilposthog.com", False),
            ("posthog_label_on_other_domain", "posthog.com.example.com", False),
            ("other_tld", "posthog.io", False),
            ("missing", None, False),
        ]
    )
    def test_host(self, _name, host, expected):
        self.assertEqual(is_posthog_owned_host(host), expected)
