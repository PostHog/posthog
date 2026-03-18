"""
This module automatically identifies recurring issues from session replay video analysis by clustering similar
session segments and creating Tasks from actionable clusters for engineering teams to investigate/solve.

Session replays are analyzed by AI to generate natural language descriptions of what users are doing in each
video segment. These descriptions are embedded as vectors and stored in ClickHouse.
This workflow periodically processes those embeddings to find patterns - if multiple users encounter the same issue
(e.g., "User clicked submit button repeatedly but nothing happened"), those segments cluster together
and become a Task for the team to fix.
"""
