import json

from posthog.session_recordings.snapshots.convert_legacy_format import _convert_legacy_format_from_lts_storage


def test_can_convert_legacy_format_from_lts_storage() -> None:
    original_format = {
        "version": "2022-12-22",
        "distinct_id": "u7uzZxFlQQtCDsNETAXPpZE2K5T2joZpITUH9AB7FXg",
        "snapshot_data_by_window_id": {
            "187a0fa19c91ca3-08a752260992e6-1d525634-16a7f0-187a0fa19ca31a2": [
                {
                    "type": 6,
                    "data": {
                        "plugin": "rrweb/console@1",
                        "payload": {
                            "level": "warn",
                            "trace": [
                                "r.value (https://app-static-prod.posthog.com/static/chunk-J4WSDDBA.js:57:55289)",
                                "d.onreadystatechange (https://app-static-prod.posthog.com/static/chunk-J4WSDDBA.js:57:54630)",
                                "XMLHttpRequest.n (https://app-static-prod.posthog.com/static/chunk-J4WSDDBA.js:153:1359)",
                            ],
                            "payload": ['"Enqueued failed request for retry in 6000"'],
                        },
                    },
                    "timestamp": 1682034038938,
                },
                {
                    "type": 4,
                    "data": {"href": "https://app.posthog.com/data-management/actions", "width": 1452, "height": 825},
                    "timestamp": 1682032957901,
                },
                {
                    "type": 2,
                    "data": {
                        "node": {
                            "type": 0,
                            "childNodes": [
                                {"type": 1, "name": "html", "publicId": "", "systemId": "", "id": 2},
                                {
                                    "type": 2,
                                    "tagName": "html",
                                    "attributes": {"lang": "en"},
                                },
                            ],
                            "id": 1,
                        },
                        "initialOffset": {"left": 0, "top": 0},
                    },
                    "timestamp": 1682032957915,
                },
            ]
        },
        "start_and_end_times_by_window_id": {
            "187a0fa19c91ca3-08a752260992e6-1d525634-16a7f0-187a0fa19ca31a2": {
                "window_id": "187a0fa19c91ca3-08a752260992e6-1d525634-16a7f0-187a0fa19ca31a2",
                "start_time": "2023-04-20 23:22:37.868000+00:00",
                "end_time": "2023-04-20 23:57:02.120000+00:00",
                "is_active": False,
            }
        },
        "segments": [
            {
                "start_time": "2023-04-20 23:22:37.868000+00:00",
                "end_time": "2023-04-20 23:57:02.120000+00:00",
                "window_id": "187a0fa19c91ca3-08a752260992e6-1d525634-16a7f0-187a0fa19ca31a2",
                "is_active": False,
            }
        ],
    }

    # now the format is jsonl (one json per line)
    # each line is a window id and its data
    data_after_conversion = {
        "window_id": "187a0fa19c91ca3-08a752260992e6-1d525634-16a7f0-187a0fa19ca31a2",
        "data": [
            {
                "type": 6,
                "data": {
                    "plugin": "rrweb/console@1",
                    "payload": {
                        "level": "warn",
                        "trace": [
                            "r.value (https://app-static-prod.posthog.com/static/chunk-J4WSDDBA.js:57:55289)",
                            "d.onreadystatechange (https://app-static-prod.posthog.com/static/chunk-J4WSDDBA.js:57:54630)",
                            "XMLHttpRequest.n (https://app-static-prod.posthog.com/static/chunk-J4WSDDBA.js:153:1359)",
                        ],
                        "payload": ['"Enqueued failed request for retry in 6000"'],
                    },
                },
                "timestamp": 1682034038938,
            },
            {
                "type": 4,
                "data": {"href": "https://app.posthog.com/data-management/actions", "width": 1452, "height": 825},
                "timestamp": 1682032957901,
            },
            {
                "type": 2,
                "data": {
                    "node": {
                        "type": 0,
                        "childNodes": [
                            {"type": 1, "name": "html", "publicId": "", "systemId": "", "id": 2},
                            {
                                "type": 2,
                                "tagName": "html",
                                "attributes": {"lang": "en"},
                            },
                        ],
                        "id": 1,
                    },
                    "initialOffset": {"left": 0, "top": 0},
                },
                "timestamp": 1682032957915,
            },
        ],
    }
    expected_after_conversion = json.dumps(data_after_conversion, separators=(",", ":"))

    assert _convert_legacy_format_from_lts_storage(original_format) == expected_after_conversion
