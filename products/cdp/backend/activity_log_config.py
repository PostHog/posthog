FIELD_EXCLUSIONS = {
    "HogFunction": [
        # Compiled output of `hog`, which the diff records on its own. For site functions the
        # transpiled JavaScript also inlines the input values that `field_with_masked_contents`
        # hides, so a diff of it would put those values back into the log.
        "bytecode",
        "transpiled",
        "icon_url",
        # Bookkeeping for the draft/revision cycle: `draft` already records that config was staged,
        # and the per-version audit lives in the revisions endpoints.
        "version",
        "draft_updated_at",
        "revisions",
    ],
}


FIELD_NAME_OVERRIDES = {
    "HogFunction": {
        "execution_order": "priority",
    },
}


FIELD_WITH_MASKED_CONTENTS = {
    "HogFunction": [
        "inputs",
        "mappings",
        # Encrypted secret inputs (Fernet ciphertext) — a diff would be noise at best and
        # leak-adjacent at worst; record that they changed, never the values.
        "encrypted_inputs",
        "draft_encrypted_inputs",
        # Full config snapshot including input values (auth headers, API keys on rows written before
        # secret inputs were encrypted) — record that a draft was staged/published/discarded, never
        # its contents. The per-version config audit lives in the revisions endpoints instead.
        "draft",
    ],
}
