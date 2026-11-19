"""Activity-log diff tuning for the `OAuthApplication` scope.

It sits next to `oauth.py` so ownership follows the model: `posthog/models/owners.yaml` gives
this file to the same team as the model. The org-level auth code has no product tree of its
own to live in. Data only, with no imports, because the activity log merges it on the
`django.setup()` path.
"""

FIELD_NAME_OVERRIDES = {
    "OAuthApplication": {
        "_provisioning_config": "provisioning config",
    },
}

FIELD_EXCLUSIONS = {
    "OAuthApplication": [
        # Secrets — never diff these, even masked.
        "client_secret",
        "hash_client_secret",
        # Reverse token relations can hold tens of thousands of rows; reading
        # through them in `changes_between` would scan the token tables.
        "oauthaccesstoken",
        "oauthidtoken",
        "oauthrefreshtoken",
        "oauthgrant",
        # Bookkeeping timestamps and FKs, not scope-ceiling intent.
        "created",
        "updated",
        "cimd_metadata_last_fetched",
        "dcr_client_id_issued_at",
        "organization",
        "user",
    ],
}
