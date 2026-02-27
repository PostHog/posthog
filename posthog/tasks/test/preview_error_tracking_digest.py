"""
Quick preview of the error tracking weekly digest email template.

Usage:
    python manage.py shell -c "exec(open('posthog/tasks/test/preview_error_tracking_digest.py').read())"
"""

import sys
import subprocess

from django.template.loader import get_template

from posthog.email import inline_css

_issue_sparkline_up = [
    {"height_percent": 10},
    {"height_percent": 25},
    {"height_percent": 40},
    {"height_percent": 55},
    {"height_percent": 70},
    {"height_percent": 85},
    {"height_percent": 100},
]
_issue_sparkline_spike = [
    {"height_percent": 30},
    {"height_percent": 45},
    {"height_percent": 100},
    {"height_percent": 80},
    {"height_percent": 65},
    {"height_percent": 70},
    {"height_percent": 50},
]
_issue_sparkline_new = [
    {"height_percent": 0},
    {"height_percent": 0},
    {"height_percent": 0},
    {"height_percent": 30},
    {"height_percent": 60},
    {"height_percent": 100},
    {"height_percent": 85},
]

project_a = {
    "team": type("Team", (), {"name": "PostHog App", "pk": 2})(),
    "exception_count": 12483,
    "exception_change": {
        "percent": 23,
        "direction": "Down",
        "color": "#2f7d4f",
        "text": "Down 23%",
        "long_text": "Down 23% from previous week",
    },
    "ingestion_failure_count": 347,
    "daily_counts": [
        {"day": "Tue", "count": 1200, "height_percent": 60},
        {"day": "Wed", "count": 800, "height_percent": 40},
        {"day": "Thu", "count": 2000, "height_percent": 100},
        {"day": "Fri", "count": 1500, "height_percent": 75},
        {"day": "Sat", "count": 400, "height_percent": 20},
        {"day": "Sun", "count": 300, "height_percent": 15},
        {"day": "Mon", "count": 1800, "height_percent": 90},
    ],
    "top_issues": [
        {
            "id": "abc",
            "name": "Error",
            "description": "Minified React error #418; visit https://reactjs.org/docs/error-decoder.html?invariant=418 for the full message",
            "occurrence_count": 155000,
            "sparkline": _issue_sparkline_spike,
            "url": "https://us.posthog.com/project/2/error_tracking/abc?utm_source=error_tracking_weekly_digest",
        },
        {
            "id": "def",
            "name": "TypeError",
            "description": "NetworkError when attempting to fetch resource.",
            "occurrence_count": 79300,
            "sparkline": _issue_sparkline_up,
            "url": "https://us.posthog.com/project/2/error_tracking/def?utm_source=error_tracking_weekly_digest",
        },
        {
            "id": "ghi",
            "name": "TypeError",
            "description": "Failed to fetch",
            "occurrence_count": 46200,
            "sparkline": _issue_sparkline_spike,
            "url": "https://us.posthog.com/project/2/error_tracking/ghi?utm_source=error_tracking_weekly_digest",
        },
        {
            "id": "jkl",
            "name": "ConcurrencyLimitExceededForRealThisTimeNoJoke",
            "description": "Exceeded maximum concurrency limit: 3 for key: api:query:per-team:133740 and this is a really long description",
            "occurrence_count": 41400,
            "sparkline": _issue_sparkline_up,
            "url": "https://us.posthog.com/project/2/error_tracking/jkl?utm_source=error_tracking_weekly_digest",
        },
        {
            "id": "mno",
            "name": "gaierror",
            "description": "[Errno -3] Temporary failure in name resolution",
            "occurrence_count": 38500,
            "sparkline": _issue_sparkline_spike,
            "url": "https://us.posthog.com/project/2/error_tracking/mno?utm_source=error_tracking_weekly_digest",
        },
    ],
    "new_issues": [
        {
            "id": "new1",
            "name": "RangeError",
            "description": "Maximum call stack size exceeded",
            "occurrence_count": 2340,
            "sparkline": _issue_sparkline_new,
            "url": "https://us.posthog.com/project/2/error_tracking/new1?utm_source=error_tracking_weekly_digest",
        },
        {
            "id": "new2",
            "name": "SyntaxError",
            "description": "Unexpected token '<' in JSON at position 0",
            "occurrence_count": 890,
            "sparkline": _issue_sparkline_new,
            "url": "https://us.posthog.com/project/2/error_tracking/new2?utm_source=error_tracking_weekly_digest",
        },
    ],
    "crash_free": {
        "total_sessions": 284532,
        "crash_free_rate": 98.80,
        "crash_free_rate_change": {
            "percent": 1,
            "direction": "Up",
            "color": "#2f7d4f",
            "text": "Up 1%",
            "long_text": "Up 1% from previous week",
        },
        "total_sessions_change": {
            "percent": 12,
            "direction": "Up",
            "color": "#2f7d4f",
            "text": "Up 12%",
            "long_text": "Up 12% from previous week",
        },
    },
    "error_tracking_url": "https://us.posthog.com/project/2/error_tracking?utm_source=error_tracking_weekly_digest",
    "ingestion_failures_url": "https://us.posthog.com/project/2/activity/explore",
}

project_b = {
    "team": type("Team", (), {"name": "Marketing Site", "pk": 7})(),
    "exception_count": 892,
    "exception_change": {
        "percent": 45,
        "direction": "Up",
        "color": "#a13232",
        "text": "Up 45%",
        "long_text": "Up 45% from previous week",
    },
    "ingestion_failure_count": 0,
    "daily_counts": [
        {"day": "Tue", "count": 80, "height_percent": 40},
        {"day": "Wed", "count": 120, "height_percent": 60},
        {"day": "Thu", "count": 200, "height_percent": 100},
        {"day": "Fri", "count": 150, "height_percent": 75},
        {"day": "Sat", "count": 90, "height_percent": 45},
        {"day": "Sun", "count": 52, "height_percent": 26},
        {"day": "Mon", "count": 200, "height_percent": 100},
    ],
    "top_issues": [
        {
            "id": "xyz",
            "name": "ChunkLoadError",
            "description": "Loading chunk 42 failed",
            "occurrence_count": 412,
            "sparkline": _issue_sparkline_up,
            "url": "https://us.posthog.com/project/7/error_tracking/xyz?utm_source=error_tracking_weekly_digest",
        },
        {
            "id": "uvw",
            "name": "AbortError",
            "description": "The operation was aborted.",
            "occurrence_count": 289,
            "sparkline": _issue_sparkline_spike,
            "url": "https://us.posthog.com/project/7/error_tracking/uvw?utm_source=error_tracking_weekly_digest",
        },
    ],
    "new_issues": [
        {
            "id": "new4",
            "name": "SecurityError",
            "description": "Blocked a frame with origin from accessing a cross-origin frame",
            "occurrence_count": 67,
            "sparkline": _issue_sparkline_new,
            "url": "https://us.posthog.com/project/7/error_tracking/new4?utm_source=error_tracking_weekly_digest",
        },
    ],
    "crash_free": {},
    "error_tracking_url": "https://us.posthog.com/project/7/error_tracking?utm_source=error_tracking_weekly_digest",
    "ingestion_failures_url": "https://us.posthog.com/project/7/activity/explore",
}

template = get_template("email/error_tracking_weekly_digest.html")
html = template.render(
    {
        "organization": type("Organization", (), {"name": "PostHog"})(),
        "project_sections": [project_a, project_b],
        "disabled_project_names": ["Staging Environment", "Internal Tools", "Experiments Sandbox"],
        "settings_url": "https://us.posthog.com/settings/user-notifications",
        "contact_support_url": "https://posthog.com/support",
        "feedback_survey_url": "https://us.posthog.com/external_surveys/019c7fd6-7cfa-0000-2b03-a8e5d4c03743?distinct_id=test@posthog.com",
    }
)

path = "/tmp/error_tracking_digest_preview.html"
with open(path, "w") as f:
    f.write(inline_css(html))

print(f"Saved to {path}")  # noqa: T201
if sys.platform == "darwin":
    subprocess.run(["open", path])
