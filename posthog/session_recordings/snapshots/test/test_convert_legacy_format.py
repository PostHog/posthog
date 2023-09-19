import json

from posthog.session_recordings.snapshots.convert_legacy_format import (
    _prepare_legacy_content,
)

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

# this is the urf-16 surrogate pass encoded, gzipped and base64 encoded version of the above
# see: https://github.com/PostHog/posthog/blob/8ff764bb573c6a98368b2ae3503890551a1c3842/posthog/session_recordings/session_recording_helpers.py#L277
legacy_compressed_original = "H4sIAMHMCWUC/9VWbXPSQBDen+L0k44FkvBS4JPV0rG+1Pex08owKQmQSgGTUMRO/7r67HOXQBFa/dQ6N3fJ3e3tPrv73Ca/fl7KllxIKLEkEslYRpg30T1x0D0piMtR37dkGz2AXCIpxpF08ezgLbCnprKD/kOO5bvsy1DeoaXyTPZw4lBa8lF25UjeygQSLWh8KVWseXIGy8dYPcDskzyXBuSeQtc+pPvWbgJ7PmQSGUBa7QaYp+gdOZU5xhkxBdidLaFSD12pQ5sPn3oYXejvorsYfSnDOwf7PiSq9LOGeQPNQ1xqjEDAnSpmZalwpUb5HiQLa7WrXhejRwwnRJEC5QQ6daVmY2k8yHBOELMpPI7yPMRoM5w5lRK0an4SjEOsPIF+E5kJNMyxNsZz4bPKaGaHVtMMuzH1bhNLjHnXojmhpSLkfSII5YE8RJxTNI14E9ZLjP4E/ibErAzoYjbByTHsFvE25p7mp4+54j3HuWV59WIACyP5irMvEM3P8gH82EO+d3HmjNaqiKeOGvU64vko516RMYiBUH2d57pD6vWx17836Cvki5OjP5LX8grsNrjeA+c3xlotFKHzblG7QFzms4w3E/P2Bn4pX76gt6DT+KA9gAd6AyJyT2fxNR91d4w1s64MnOM9oud657SpVrV7hWZ4GsGf0PpzDixbxFgDL7RG6X3UUVmio55avWuVtXdtQBQ9ezvWx31zfDNtBcx8ViblnSIdYb3Eu5XaiprY/M9Yk1SX8aFCfm/Teoi9PlHoXp3V5m8j4MF35VwDM3dtBLy1ERiRQ2E+Xz7h8ITyRrMZoHob2WRDPXMpPyLCcCmm56w/hkVTVLEhGXmQfzGy2m5uskZwdS+r494NnqWM/+EN1n3mN4a2U+BIc09MpTR1w5wLWSOVf+1r9l2bD+VrxKxorXwDBvWgK7SZyypvz84di29s8+b8A7MXeXXJhrY9aU7E/Ab6/OJ1iFqfC633/6t4ae/En+juGttqlLOoLv8bGRQV/hs5qGAeq6eiaeJtB7WizlyauvaYY5Oj0b+asdt1m++K7hf5V+Zs1B0x/1kNurDae2SscvUqZ1II3mdVa/lu/8/e319O3Z4XveO/AS7WeNOWCwAA"

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


def test_can_prepare_legacy_content_for_saving() -> None:
    expected_after_conversion = json.dumps(data_after_conversion, separators=(",", ":"))
    assert _prepare_legacy_content(legacy_compressed_original) == expected_after_conversion
