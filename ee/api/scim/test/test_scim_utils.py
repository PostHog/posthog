from parameterized import parameterized

from ee.api.scim.utils import mask_email, mask_pii_value, mask_scim_filter, mask_scim_payload, mask_string


class TestMaskString:
    @parameterized.expand(
        [
            ("John", "J***n"),
            ("A", "*"),
            ("AB", "**"),
            ("ABC", "A***C"),
            ("hello", "h***o"),
        ]
    )
    def test_mask_string(self, input_value, expected):
        assert mask_string(input_value) == expected


class TestMaskEmail:
    @parameterized.expand(
        [
            ("john.doe@example.com", "j***e@example.com"),
            ("a@b.co", "*@b.co"),
            ("ab@domain.org", "**@domain.org"),
            ("test@domain.org", "t***t@domain.org"),
            ("no-at-sign", "n***n"),
        ]
    )
    def test_mask_email(self, input_value, expected):
        assert mask_email(input_value) == expected


class TestMaskPiiValue:
    @parameterized.expand(
        [
            ("john@example.com", "j***n@example.com"),
            ("John", "J***n"),
            ("", ""),
            (None, None),
            (123, 123),
            (True, True),
        ]
    )
    def test_mask_pii_value(self, input_value, expected):
        assert mask_pii_value(input_value) == expected


class TestMaskScimPayload:
    def test_masks_user_create_payload(self):
        payload = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "john.doe@example.com",
            "name": {"givenName": "John", "familyName": "Doe"},
            "emails": [{"value": "john.doe@example.com", "primary": True}],
            "active": True,
        }

        assert mask_scim_payload(payload) == {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "j***e@example.com",
            "name": {"givenName": "J***n", "familyName": "D***e"},
            "emails": [{"value": "j***e@example.com", "primary": True}],
            "active": True,
        }

    def test_masks_patch_operations(self):
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "userName", "value": "new.email@example.com"},
                {"op": "replace", "path": "active", "value": False},
                {"op": "replace", "path": "name", "value": {"givenName": "Jane", "familyName": "Smith"}},
            ],
        }

        assert mask_scim_payload(payload) == {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "userName", "value": "n***l@example.com"},
                {"op": "replace", "path": "active", "value": False},
                {"op": "replace", "path": "name", "value": {"givenName": "J***e", "familyName": "S***h"}},
            ],
        }

    def test_masks_group_with_members(self):
        payload = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "Engineering Team",
            "members": [
                {"value": "user-123", "display": "john.doe@example.com"},
                {"value": "user-456", "display": "jane.smith@example.com"},
            ],
        }

        assert mask_scim_payload(payload) == {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "E***m",
            "members": [
                {"value": "u***3", "display": "j***e@example.com"},
                {"value": "u***6", "display": "j***h@example.com"},
            ],
        }

    def test_preserves_non_pii_fields(self):
        payload = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "id": "12345",
            "externalId": "ext-123",
            "meta": {"resourceType": "User", "created": "2024-01-01T00:00:00Z"},
        }

        assert mask_scim_payload(payload) == payload

    def test_handles_empty_payload(self):
        assert mask_scim_payload({}) == {}
        assert mask_scim_payload([]) == []
        assert mask_scim_payload(None) is None


class TestMaskScimFilter:
    @parameterized.expand(
        [
            ('userName eq "alex@posthog.com"', 'userName eq "a***x@posthog.com"'),
            ('emails.value eq "test@example.com"', 'emails.value eq "t***t@example.com"'),
            ('displayName eq "John Doe"', 'displayName eq "J***e"'),
            ('userName eq "a@b.com"', 'userName eq "*@b.com"'),
            ("active eq true", "active eq true"),
            ('userName eq "test@x.com" and active eq true', 'userName eq "t***t@x.com" and active eq true'),
            # escaped quotes and backslashes
            (r'displayName eq "John \"The Man\" Doe"', r'displayName eq "J***e"'),
            (r'displayName eq "path\\to\\file"', r'displayName eq "p***e"'),
        ]
    )
    def test_mask_scim_filter(self, input_value, expected):
        assert mask_scim_filter(input_value) == expected
