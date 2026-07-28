"""This module contains test utilities used in all batch export tests."""

# Far enough above any real test team's sequential pk that synthetic rows generated for a
# "different team" can never land on a team a later test asserts counts for.
OTHER_TEAM_ID_OFFSET = 1_000_000_000
