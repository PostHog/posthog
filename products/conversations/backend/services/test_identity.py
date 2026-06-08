from posthog.test.base import BaseTest

from products.conversations.backend.services.identity import compute_identity_hash, verify_identity_hash


class TestIdentityService(BaseTest):
    def test_compute_identity_hash_deterministic(self):
        h1 = compute_identity_hash("user_123", "secret")
        h2 = compute_identity_hash("user_123", "secret")
        assert h1 == h2

    def test_compute_identity_hash_different_inputs(self):
        h1 = compute_identity_hash("user_123", "secret")
        h2 = compute_identity_hash("user_456", "secret")
        assert h1 != h2

    def test_compute_identity_hash_different_secrets(self):
        h1 = compute_identity_hash("user_123", "secret_a")
        h2 = compute_identity_hash("user_123", "secret_b")
        assert h1 != h2

    def test_verify_identity_hash_valid(self):
        h = compute_identity_hash("user_123", "secret")
        assert verify_identity_hash("user_123", h, "secret")

    def test_verify_identity_hash_invalid(self):
        assert not verify_identity_hash("user_123", "badhash", "secret")

    def test_verify_identity_hash_wrong_secret(self):
        h = compute_identity_hash("user_123", "secret_a")
        assert not verify_identity_hash("user_123", h, "secret_b")

    def test_distinct_id_is_case_sensitive(self):
        h_lower = compute_identity_hash("User_123", "secret")
        h_upper = compute_identity_hash("user_123", "secret")
        assert h_lower != h_upper
        assert not verify_identity_hash("user_123", h_lower, "secret")

    def test_hash_is_64_char_hex(self):
        h = compute_identity_hash("user_123", "secret")
        assert len(h) == 64
        int(h, 16)  # should not raise
