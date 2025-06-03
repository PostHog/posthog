# List of default playlists to create when a new project is created
#
# Each playlist is a dictionary with the following keys:
# - name: The name of the playlist
# - filters: The filters to apply to the playlist
# - description: The description of the playlist
DEFAULT_PLAYLISTS = [
    {
        "name": "Recordings of Gmail users",
        "filters": {
            "order": "start_time",
            "date_to": "null",
            "duration": [{"key": "active_seconds", "type": "recording", "value": 5, "operator": "gt"}],
            "date_from": "-3d",
            "filter_group": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "$initial_utm_source", "type": "person", "value": ["google"], "operator": "exact"}
                        ],
                    }
                ],
            },
            "filter_test_accounts": "true",
        },
        "description": "Recordings of users with Gmail addresses",
    },
    {
        "name": "Mobile device recordings",
        "filters": {
            "order": "start_time",
            "date_to": "null",
            "duration": [{"key": "active_seconds", "type": "recording", "value": 5, "operator": "gt"}],
            "date_from": "-3d",
            "filter_group": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "snapshot_source", "type": "recording", "value": ["mobile"], "operator": "exact"}
                        ],
                    }
                ],
            },
            "filter_test_accounts": "true",
        },
        "description": "Recordings of users on mobile devices",
    },
    {
        "name": "Recordings with Rage Clicks",
        "filters": {"events": [{"id": "$rageclick", "type": "events", "order": 0}]},
        "description": "Recordings containing rage clicks. Most likely to be from users who are frustrated.",
    },
    {
        "name": "Recordings of people from Google Ads",
        "filters": {
            "order": "start_time",
            "date_to": "null",
            "duration": [{"key": "active_seconds", "type": "recording", "value": 5, "operator": "gt"}],
            "date_from": "-3d",
            "filter_group": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "$initial_utm_source", "type": "person", "value": ["google"], "operator": "exact"}
                        ],
                    }
                ],
            },
            "filter_test_accounts": "true",
        },
        "description": "Recordings of users who came from Google Ads",
    },
    {
        "name": "Recordings with 5+ console log errors",
        "filters": {
            "order": "start_time",
            "date_to": "null",
            "duration": [{"key": "active_seconds", "type": "recording", "value": 5, "operator": "gt"}],
            "date_from": "-3d",
            "filter_group": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "level", "type": "log_entry", "value": ["error"], "operator": "exact"},
                            {"key": "message", "type": "log_entry", "value": "5", "operator": "gt"},
                        ],
                    }
                ],
            },
            "filter_test_accounts": "true",
        },
        "description": "List of recordings where users faced 5+ console errors",
    },
    {
        "name": "All recordings",
        "filters": {
            "order": "start_time",
            "date_to": "null",
            "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "gt"}],
            "date_from": "-3d",
            "filter_group": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            "filter_test_accounts": "true",
        },
        "description": "All session recordings longer than 1 minute",
    },
]

DEFAULT_PLAYLIST_NAMES = [p["name"] for p in DEFAULT_PLAYLISTS]
