FIELD_EXCLUSIONS = {
    # The subject is the identity of a rule and never changes. The receiver names it in the
    # context, so the diff does not load the role and the membership for both sides.
    "AccessControl": ["organization_member", "role"],
}
