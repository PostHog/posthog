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
        "ingestion_failure_count": 347,
        "daily_counts": [
            {"day": "Tue", "count": 1200, "height_pct": 60},
            {"day": "Wed", "count": 800, "height_pct": 40},
            {"day": "Thu", "count": 2000, "height_pct": 100},
            {"day": "Fri", "count": 1500, "height_pct": 75},
            {"day": "Sat", "count": 400, "height_pct": 20},
            {"day": "Sun", "count": 300, "height_pct": 15},
            {"day": "Mon", "count": 1800, "height_pct": 90},
        ],
        "top_issues": [
            {
                "id": "abc",
                "name": "Error",
                "description": "Minified React error #418; visit https://reactjs.org/docs/error-decoder.html",
                "occurrence_count": 155000,
                "sparkline": [
                    {"height_pct": 70},
                    {"height_pct": 85},
                    {"height_pct": 60},
                    {"height_pct": 90},
                    {"height_pct": 100},
                    {"height_pct": 75},
                    {"height_pct": 80},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/abc",
            },
            {
                "id": "def",
                "name": "TypeError",
                "description": "NetworkError when attempting to fetch resource.",
                "occurrence_count": 79300,
                "sparkline": [
                    {"height_pct": 40},
                    {"height_pct": 55},
                    {"height_pct": 100},
                    {"height_pct": 80},
                    {"height_pct": 65},
                    {"height_pct": 70},
                    {"height_pct": 50},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/def",
            },
            {
                "id": "ghi",
                "name": "TypeError",
                "description": "Failed to fetch",
                "occurrence_count": 46200,
                "sparkline": [
                    {"height_pct": 30},
                    {"height_pct": 45},
                    {"height_pct": 60},
                    {"height_pct": 100},
                    {"height_pct": 80},
                    {"height_pct": 55},
                    {"height_pct": 40},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/ghi",
            },
            {
                "id": "jkl",
                "name": "ConcurrencyLimitExceeded",
                "description": "Exceeded maximum concurrency limit: 3 for key: api:query:per-team:133740",
                "occurrence_count": 41400,
                "sparkline": [
                    {"height_pct": 10},
                    {"height_pct": 15},
                    {"height_pct": 5},
                    {"height_pct": 20},
                    {"height_pct": 100},
                    {"height_pct": 80},
                    {"height_pct": 60},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/jkl",
            },
            {
                "id": "mno",
                "name": "gaierror",
                "description": "[Errno -3] Temporary failure in name resolution",
                "occurrence_count": 38500,
                "sparkline": [
                    {"height_pct": 90},
                    {"height_pct": 70},
                    {"height_pct": 50},
                    {"height_pct": 30},
                    {"height_pct": 20},
                    {"height_pct": 100},
                    {"height_pct": 85},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/mno",
            },
        ],
        "new_issues": [
            {
                "id": "new1",
                "name": "RangeError",
                "description": "Maximum call stack size exceeded",
                "occurrence_count": 2340,
                "sparkline": [
                    {"height_pct": 0},
                    {"height_pct": 0},
                    {"height_pct": 0},
                    {"height_pct": 30},
                    {"height_pct": 60},
                    {"height_pct": 100},
                    {"height_pct": 85},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/new1",
            },
            {
                "id": "new2",
                "name": "SyntaxError",
                "description": "Unexpected token '<' in JSON at position 0",
                "occurrence_count": 890,
                "sparkline": [
                    {"height_pct": 0},
                    {"height_pct": 0},
                    {"height_pct": 0},
                    {"height_pct": 0},
                    {"height_pct": 20},
                    {"height_pct": 100},
                    {"height_pct": 70},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/new2",
            },
            {
                "id": "new3",
                "name": "NotFoundError",
                "description": "The object can not be found here.",
                "occurrence_count": 156,
                "sparkline": [
                    {"height_pct": 0},
                    {"height_pct": 0},
                    {"height_pct": 0},
                    {"height_pct": 0},
                    {"height_pct": 0},
                    {"height_pct": 100},
                    {"height_pct": 45},
                ],
                "url": "https://us.posthog.com/project/2/error_tracking/new3",
            },
        ],
        "error_tracking_url": "https://us.posthog.com/project/2/error_tracking",
        "ingestion_failures_url": "https://us.posthog.com/project/2/activity/explore",
        "contact_support_url": "https://posthog.com/support",
    }
)

path = "/tmp/error_tracking_digest_preview.html"
with open(path, "w") as f:
    f.write(inline_css(html))

print(f"Saved to {path}")  # noqa: T201
if sys.platform == "darwin":
    subprocess.run(["open", path])
