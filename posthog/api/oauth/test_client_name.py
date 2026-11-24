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
from posthog.api.oauth.dcr import DCRRequestSerializer


class TestSanitizeClientName(TestCase):
    @parameterized.expand(
        [
            ("plain_name", "My Analytics App", "My Analytics App"),
            ("script_tag", "<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
            ("ampersand_in_middle", "Tom & Jerry", "Tom &amp; Jerry"),
            ("quote", "John's App", "John&#x27;s App"),
            ("bidi_override_dropped", "\u202egoHtsoP", "goHtsoP"),
            ("surrounding_whitespace_trimmed", " Acme ", "Acme"),
            ("emoji_joiner_kept", "\U0001f469\u200d\U0001f4bb Dev Tools", "\U0001f469\u200d\U0001f4bb Dev Tools"),
        ]
    )
    def test_sanitizes_short_names_without_truncation(self, _name, value, expected):
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
            ("leading_space", " PostHog Wizard"),
            ("zero_width_space_prefix", "\u200bPostHog MCP"),
            ("word_joiner_prefix", "\u2060PostHog MCP"),
            ("hangul_filler_prefix", "\u3164PostHog MCP"),
            ("leading_punctuation", "[PostHog] Wizard"),
            ("split_by_space", "Post Hog Wizard"),
            ("cyrillic_er", "\u0420ostHog Wizard"),
            ("cyrillic_capitals", "\u0420\u041e\u0405\u0422\u041d\u041e\u050c"),
            ("greek_rho_and_omicron", "\u03a1\u03bfstHog Wizard"),
            ("coptic_o", "P\u2c9fstHog Wizard"),
            ("cherokee_small_letters", "\uabb2ostHog Wizard"),
            ("bengali_zero", "P\u09e6stHog Wizard"),
            ("full_width", "\uff30\uff4f\uff53\uff54\uff28\uff4f\uff47 Wizard"),
            ("mathematical_bold", "\U0001d40f\U0001d428\U0001d42c\U0001d42d\U0001d407\U0001d428\U0001d420"),
            ("accented", "P\u00f6stH\u00f6g Wizard"),
            ("cyrillic_o_in_blocked_word", "\u041efficial MCP Client"),
            ("zero_width_space_in_blocked_word", "Acme Veri\u200bfied"),
            ("trademark_sign_prefix", "\u2122PostHog Wizard"),
            ("numero_sign_prefix", "\u2116PostHog Wizard"),
            ("circled_p", "\u24c5ostHog Wizard"),
            ("p_with_middle_tilde", "\u1d71ostHog Wizard"),
            ("emoji_circle_for_o", "P\U0001f534stHog Wizard"),
            ("bullet_between_words", "Post\u2022Hog Wizard"),
            ("negative_circled_p_prefix", "\U0001f15fostHog Wizard"),
            ("myanmar_wa", "P\u101dstH\u101dg MCP"),
            ("arabic_indic_five_for_o", "P\u0665stHog MCP"),
            ("egyptian_full_blank_prefix", "\U00013441PostHog MCP"),
            ("cyrillic_e_in_blocked_word", "My V\u0435rified App"),
            ("greek_nu_in_blocked_word", "Acme \u03bderified Client"),
            ("hyphen_inside_blocked_word", "Acme Veri-fied Client"),
            ("cyrillic_barred_o", "P\u04e8stHog Wizard"),
            ("unassigned_invisible_in_blocked_word", "Acme Veri\u2065fied"),
        ]
    )
    def test_rejects_impersonating_names(self, _name, value):
        with self.assertRaises(serializers.ValidationError):
            validate_client_name(value)

    @parameterized.expand(
        [
            ("contains_but_not_prefixed_by_posthog", "Claude Code (posthog-local)"),
            ("unrelated_name", "My Analytics Dashboard"),
            ("posthog_after_the_client_name", "Claude for PostHog"),
            ("shares_a_prefix_with_posthog", "Postman Collections"),
            ("cyrillic_name", "\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430"),
            ("cyrillic_name_ending_with_posthog", "\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430 PostHog"),
            ("cjk_name", "\u6570\u636e\u5206\u6790 Client"),
            ("emoji_name", "\U0001f994 Hedgehog Helper"),
            ("blocked_word_split_across_words", "Trust Edition Sync"),
        ]
    )
    def test_accepts_valid_names(self, _name, value):
        validate_client_name(value)

    def test_overlong_name_gets_only_the_length_error(self):
        serializer = DCRRequestSerializer(data={"client_name": "PostHog " + "x" * CLIENT_NAME_MAX_LENGTH})

        self.assertFalse(serializer.is_valid())
        self.assertEqual([error.code for error in serializer.errors["client_name"]], ["max_length"])


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
            ("hangul_filler", "Acme Post\u3164Hog"),
            ("coptic_o", "Acme P\u2c9fstHog"),
            ("armenian_ho_and_co", "Acme Post\u0570o\u0581"),
            ("bengali_zero", "Acme P\u09e6stHog"),
            ("modifier_apostrophe", "Acme Post\u02bcHog"),
            ("combining_mark_that_casefold_turns_into_iota", "Acme Post\u0345Hog"),
            ("black_circle_for_o", "Acme P\u2b24stHog"),
            ("bullet_for_o", "Acme P\u2022stHog"),
            ("ideographic_full_stop_for_o", "Acme P\u3002stHog"),
            ("bullet_between_words", "Acme Post\u2022Hog"),
            ("non_latin_letter_between_words", "Acme Post\u05d0Hog"),
            ("blocked_word", "Acme Trusted Client"),
            ("blocked_word_with_cyrillic_o", "Acme \u041efficial Client"),
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
