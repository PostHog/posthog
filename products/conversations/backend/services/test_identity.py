from django.test import SimpleTestCase

from products.conversations.backend.services.identity import (
    canonicalize_claim_value,
    compute_identity_claim_hash,
    compute_identity_hash,
    verify_identity_claim_hash,
    verify_identity_hash,
)


class TestIdentityService(SimpleTestCase):
    def test_compute_identity_hash_deterministic(self):
        h1 = compute_identity_hash("user_123", "secret")
        h2 = compute_identity_hash("user_123", "secret")
        self.assertEqual(h1, h2)

    def test_compute_identity_hash_different_inputs(self):
        h1 = compute_identity_hash("user_123", "secret")
        h2 = compute_identity_hash("user_456", "secret")
        self.assertNotEqual(h1, h2)

    def test_compute_identity_hash_different_secrets(self):
        h1 = compute_identity_hash("user_123", "secret_a")
        h2 = compute_identity_hash("user_123", "secret_b")
        self.assertNotEqual(h1, h2)

    def test_verify_identity_hash_valid(self):
        h = compute_identity_hash("user_123", "secret")
        self.assertTrue(verify_identity_hash("user_123", h, "secret"))

    def test_verify_identity_hash_invalid(self):
        self.assertFalse(verify_identity_hash("user_123", "badhash", "secret"))

    def test_verify_identity_hash_wrong_secret(self):
        h = compute_identity_hash("user_123", "secret_a")
        self.assertFalse(verify_identity_hash("user_123", h, "secret_b"))

    def test_distinct_id_is_case_sensitive(self):
        h_lower = compute_identity_hash("User_123", "secret")
        h_upper = compute_identity_hash("user_123", "secret")
        self.assertNotEqual(h_lower, h_upper)
        self.assertFalse(verify_identity_hash("user_123", h_lower, "secret"))

    def test_hash_is_64_char_hex(self):
        h = compute_identity_hash("user_123", "secret")
        self.assertEqual(len(h), 64)
        int(h, 16)  # should not raise


class TestIdentityClaimHash(SimpleTestCase):
    def test_claim_hash_verifies(self):
        h = compute_identity_claim_hash("user_123", "email", "a@example.com", "secret")
        self.assertTrue(verify_identity_claim_hash("user_123", "email", "a@example.com", h, "secret"))

    def test_claim_hash_bound_to_distinct_id(self):
        h = compute_identity_claim_hash("user_123", "email", "a@example.com", "secret")
        self.assertFalse(verify_identity_claim_hash("user_456", "email", "a@example.com", h, "secret"))

    def test_claim_hash_bound_to_field(self):
        # A hash minted for email must not verify when presented as another field.
        h = compute_identity_claim_hash("user_123", "email", "a@example.com", "secret")
        self.assertFalse(verify_identity_claim_hash("user_123", "phone", "a@example.com", h, "secret"))

    def test_claim_hash_bound_to_version(self):
        h = compute_identity_claim_hash("user_123", "email", "a@example.com", "secret", version="v1")
        self.assertFalse(verify_identity_claim_hash("user_123", "email", "a@example.com", h, "secret", version="v2"))

    def test_email_canonicalized_before_signing(self):
        # Different-cased / padded input signs to the same hash as the canonical form.
        h_raw = compute_identity_claim_hash("user_123", "email", "  A@Example.COM ", "secret")
        h_canonical = compute_identity_claim_hash("user_123", "email", "a@example.com", "secret")
        self.assertEqual(h_raw, h_canonical)
        self.assertTrue(verify_identity_claim_hash("user_123", "email", "  A@Example.COM ", h_canonical, "secret"))

    def test_unknown_field_cannot_be_signed(self):
        with self.assertRaises(ValueError):
            compute_identity_claim_hash("user_123", "org", "acme", "secret")

    def test_nul_in_claim_part_cannot_be_signed(self):
        with self.assertRaises(ValueError):
            compute_identity_claim_hash("user_123\x00admin", "email", "a@example.com", "secret")

    def test_canonicalize_email(self):
        self.assertEqual(canonicalize_claim_value("email", "  A@Example.COM "), "a@example.com")
