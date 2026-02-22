"""
Quick preview of the error tracking weekly digest email template.

Usage:
    python manage.py shell -c "exec(open('posthog/tasks/test/preview_error_tracking_digest.py').read())"
"""

import sys
import subprocess

from django.template.loader import get_template

from posthog.email import inline_css

template = get_template("email/error_tracking_weekly_digest.html")
html = template.render(
    {
        "team": type("Team", (), {"name": "My Project", "pk": 2})(),
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
                "description": "Minified React error #418; visit https://reactjs.org/docs/error-decoder.html?invariant=418 for the full message or use the non-minified dev environment for full errors and additional helpful warnings",
                "occurrence_count": 155000,
                "sparkline": [
                    {"height_percent": 70},
                    {"height_percent": 85},
                    {"height_percent": 60},
                    {"height_percent": 90},
                    {"height_percent": 100},
                    {"height_percent": 75},
                    {"height_percent": 80},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/abc?utm_source=error_tracking_weekly_digest",
            },
            {
                "id": "def",
                "name": "TypeError",
                "description": "NetworkError when attempting to fetch resource.",
                "occurrence_count": 79300,
                "sparkline": [
                    {"height_percent": 40},
                    {"height_percent": 55},
                    {"height_percent": 100},
                    {"height_percent": 80},
                    {"height_percent": 65},
                    {"height_percent": 70},
                    {"height_percent": 50},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/def?utm_source=error_tracking_weekly_digest",
            },
            {
                "id": "ghi",
                "name": "TypeError",
                "description": "Failed to fetch",
                "occurrence_count": 46200,
                "sparkline": [
                    {"height_percent": 30},
                    {"height_percent": 45},
                    {"height_percent": 60},
                    {"height_percent": 100},
                    {"height_percent": 80},
                    {"height_percent": 55},
                    {"height_percent": 40},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/ghi?utm_source=error_tracking_weekly_digest",
            },
            {
                "id": "jkl",
                "name": "ConcurrencyLimitExceededForRealThisTimeNoJoke",
                "description": "Exceeded maximum concurrency limit: 3 for key: api:query:per-team:133740 and this is a really long description that should be truncated",
                "occurrence_count": 41400,
                "sparkline": [
                    {"height_percent": 10},
                    {"height_percent": 15},
                    {"height_percent": 5},
                    {"height_percent": 20},
                    {"height_percent": 100},
                    {"height_percent": 80},
                    {"height_percent": 60},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/jkl?utm_source=error_tracking_weekly_digest",
            },
            {
                "id": "mno",
                "name": "gaierror",
                "description": "[Errno -3] Temporary failure in name resolution",
                "occurrence_count": 38500,
                "sparkline": [
                    {"height_percent": 90},
                    {"height_percent": 70},
                    {"height_percent": 50},
                    {"height_percent": 30},
                    {"height_percent": 20},
                    {"height_percent": 100},
                    {"height_percent": 85},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/mno?utm_source=error_tracking_weekly_digest",
            },
        ],
        "new_issues": [
            {
                "id": "new1",
                "name": "RangeError",
                "description": "Maximum call stack size exceeded",
                "occurrence_count": 2340,
                "sparkline": [
                    {"height_percent": 0},
                    {"height_percent": 0},
                    {"height_percent": 0},
                    {"height_percent": 30},
                    {"height_percent": 60},
                    {"height_percent": 100},
                    {"height_percent": 85},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/new1?utm_source=error_tracking_weekly_digest",
            },
            {
                "id": "new2",
                "name": "SyntaxError",
                "description": "Unexpected token '<' in JSON at position 0",
                "occurrence_count": 890,
                "sparkline": [
                    {"height_percent": 0},
                    {"height_percent": 0},
                    {"height_percent": 0},
                    {"height_percent": 0},
                    {"height_percent": 20},
                    {"height_percent": 100},
                    {"height_percent": 70},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/new2?utm_source=error_tracking_weekly_digest",
            },
            {
                "id": "new3",
                "name": "NotFoundError",
                "description": "The object can not be found here.",
                "occurrence_count": 156,
                "sparkline": [
                    {"height_percent": 0},
                    {"height_percent": 0},
                    {"height_percent": 0},
                    {"height_percent": 0},
                    {"height_percent": 0},
                    {"height_percent": 100},
                    {"height_percent": 45},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/new3?utm_source=error_tracking_weekly_digest",
            },
        ],
        "crash_free": {
            "total_sessions": 284532,
            "crash_sessions": 3421,
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
            "crash_sessions_change": {
                "percent": 8,
                "direction": "Up",
                "color": "#a13232",
                "text": "Up 8%",
                "long_text": "Up 8% from previous week",
            },
        },
        "error_tracking_url": "https://us.posthog.com/project/2/error_tracking?utm_source=error_tracking_weekly_digest",
        "ingestion_failures_url": "https://us.posthog.com/project/2/activity/explore",
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
