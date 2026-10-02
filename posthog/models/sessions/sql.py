# V1 Sessions table
TABLE_BASE_NAME = "sessions"


def SESSIONS_DATA_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


# Only teams that were grandfathered into the V1 sessions table are allowed to use it. Everyone else should use V2,
# i.e. raw_sessions. These teams were those who were seen to have changed their session table version in these metabase
# queries:
# US: https://metabase.prod-us.posthog.dev/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7InR5cGUiOiJuYXRpdmUiLCJuYXRpdmUiOnsicXVlcnkiOiJTRUxFQ1QgdGVhbV9pZCwgc1xuRlJPTSAoXG4gICAgU0VMRUNUIG1vZGlmaWVycy0-PidzZXNzaW9uVGFibGVWZXJzaW9uJyBBUyBzLCBpZCBhcyB0ZWFtX2lkXG4gICAgRlJPTSBwb3N0aG9nX3RlYW1cbikgc3ViXG5XSEVSRSBzICE9ICcnIiwidGVtcGxhdGUtdGFncyI6e319LCJkYXRhYmFzZSI6MzR9LCJkaXNwbGF5IjoidGFibGUiLCJwYXJhbWV0ZXJzIjpbXSwidmlzdWFsaXphdGlvbl9zZXR0aW5ncyI6e319
# EU: https://metabase.prod-eu.posthog.dev/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7InR5cGUiOiJuYXRpdmUiLCJuYXRpdmUiOnsicXVlcnkiOiJTRUxFQ1QgdGVhbV9pZCwgc1xuRlJPTSAoXG4gICAgU0VMRUNUIG1vZGlmaWVycy0-PidzZXNzaW9uVGFibGVWZXJzaW9uJyBBUyBzLCBpZCBhcyB0ZWFtX2lkXG4gICAgRlJPTSBwb3N0aG9nX3RlYW1cbikgc3ViXG5XSEVSRSBzICE9ICcnIiwidGVtcGxhdGUtdGFncyI6e319LCJkYXRhYmFzZSI6MzR9LCJkaXNwbGF5IjoidGFibGUiLCJwYXJhbWV0ZXJzIjpbXSwidmlzdWFsaXphdGlvbl9zZXR0aW5ncyI6e319
# or had contacted support about an issue.
# This list exists because we want to reduce the number of writes happening to this table, and so we don't write to it
# for any team not in this list. Adding a team to this is possible if needed, but would require changing this MV in
# production and backfilling this table from events.
ALLOWED_TEAM_IDS = [
    # posthog
    1,
    2,
    # US query
    13610,  # zendesk: https://posthoghelp.zendesk.com/agent/tickets/18001
    19279,
    21173,
    29929,
    32050,
    # EU query
    9910,
    11775,
    21129,
    31490,
]
