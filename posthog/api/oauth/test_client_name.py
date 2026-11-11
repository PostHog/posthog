from unittest import TestCase

from parameterized import parameterized
from rest_framework import serializers

from posthog.api.oauth.client_name import (
    CLIENT_NAME_MAX_LENGTH,
    is_posthog_controlled_url,
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
            ("cyrillic_o", "P\u043estHog Analytics"),
            ("greek_omicron_and_cyrillic_es", "Po\u0455tH\u03bfg"),
            ("cyrillic_capitals", "\u0420OST\u041dOG"),
            ("digit_zero", "P0stHog"),
            ("accented", "P\u00f6stH\u00f6g"),
            ("full_width", "\uff30\uff4f\uff53\uff54\uff28\uff4f\uff47"),
            ("zero_width_space", "Post\u200bHog"),
            ("blocked_word", "Acme Trusted Client"),
        ]
    )
    def test_rejects_on_other_domains(self, _name, value):
        with self.assertRaises(serializers.ValidationError):
            validate_cimd_client_name(value, "https://app.example.com/client.json")

    def test_error_does_not_reveal_the_exemption(self):
        with self.assertRaises(serializers.ValidationError) as ctx:
            validate_cimd_client_name("Claude for PostHog", "https://app.example.com/client.json")
        self.assertEqual(ctx.exception.detail, ["Client name cannot contain 'PostHog'"])

    def test_allows_posthog_on_posthog_controlled_urls(self):
        validate_cimd_client_name("PostHog Artifacts", "https://artifacts.posthog.com/oauth/client-metadata.json")

    def test_blocked_words_apply_on_posthog_controlled_urls(self):
        with self.assertRaises(serializers.ValidationError):
            validate_cimd_client_name("PostHog Official", "https://posthog.com/client.json")

    def test_accepts_unrelated_name(self):
        validate_cimd_client_name("Acme Analytics", "https://app.example.com/client.json")


class TestIsPosthogControlledUrl(TestCase):
    @parameterized.expand(
        [
            ("apex", "https://posthog.com/.well-known/oauth/hogli/client-metadata.json", True),
            ("subdomain", "https://artifacts.posthog.com/oauth/client-metadata.json", True),
            ("uppercase_and_trailing_dot", "https://Artifacts.PostHog.com./client.json", True),
            ("net", "https://tools.posthog.net/client.json", True),
            ("dev", "https://posthog.dev/client.json", True),
            ("webhooks_host", "https://webhooks.us.posthog.com/public/webhooks/abc", False),
            ("webhooks_host_other_path", "https://webhooks.eu.posthog.com/client.json", False),
            ("hooks_host", "https://hooks.posthog.com/client.json", False),
            ("public_path_on_app_host", "https://app.dev.posthog.dev/public/webhooks/abc", False),
            ("public_path_mixed_case", "https://us.posthog.com/Public/webhooks/abc", False),
            ("public_path_percent_encoded", "https://us.posthog.com/%70ublic/webhooks/abc", False),
            ("public_path_after_dot_segments", "https://us.posthog.com/a/../public/webhooks/abc", False),
            ("public_path_double_slash", "https://us.posthog.com//public/webhooks/abc", False),
            ("lookalike", "https://evilposthog.com/client.json", False),
            ("posthog_label_on_other_domain", "https://posthog.com.example.com/client.json", False),
            ("other_tld", "https://posthog.io/client.json", False),
        ]
    )
    def test_url(self, _name, url, expected):
        self.assertEqual(is_posthog_controlled_url(url), expected)
