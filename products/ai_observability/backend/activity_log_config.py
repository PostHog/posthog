FIELD_EXCLUSIONS = {
    "Evaluation": [
        # The fail-closed relation cannot be resolved outside a team scope; the handler diffs IDs instead.
        "directory",
        # Reverse relations — auto-managed by FK creates, not user intent.
        "reports",
        "backfills",
    ],
}
