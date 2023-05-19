prompts_config = [
    {
        "key": "session-recording-playlist-announcement",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "title": "Save your filters as playlists!",
                "text": "You can now save your search as a playlist which will keep up to date as new recordings come in matching the filters you set. Sharing with your team has never been easier!",
                "placement": "bottom-start",
                "reference": "save-recordings-playlist-button",
            }
        ],
        "rule": {"path": {"must_match": ["/replay/recent"]}},
        "type": "one-off",
    },
]
