from datetime import datetime, timedelta
import random
from typing import Any

from posthog.cloud_utils import get_api_host
from .serializers import (
    WebAnalyticsOverviewResponseSerializer,
    WebAnalyticsTrendResponseSerializer,
    WebAnalyticsBreakdownResponseSerializer,
    WebAnalyticsTrendPointSerializer,
)


class WebAnalyticsDataFactory:
    def __init__(self):
        self.metric_ranges = {
            "visitors": (500, 3000),
            "views": (800, 8000),
            "sessions": (400, 2500),
        }

        self.breakdown_values = {
            "page": ["/home", "/products", "/about", "/pricing", "/blog", "/contact", "/features", "/login", "/signup"],
            "entry_page": ["/home", "/products", "/blog", "/pricing", "/about", "/features"],
            "exit_page": ["/contact", "/pricing", "/checkout", "/home", "/products"],
            "referrer": ["google.com", "facebook.com", "direct", "twitter.com", "linkedin.com"],
            "utm_source": ["google", "facebook", "twitter", "linkedin", "email"],
            "utm_campaign": ["summer_sale", "product_launch", "brand_awareness", "retargeting"],
            "utm_medium": ["cpc", "organic", "email", "social", "referral"],
            "browser": ["Chrome", "Safari", "Firefox", "Edge", "Opera"],
            "os": ["Windows", "macOS", "iOS", "Android", "Linux"],
            "device": ["Desktop", "Mobile", "Tablet"],
            "country": ["US", "GB", "CA", "DE", "FR", "AU", "JP", "BR"],
            "region": ["California, US", "Texas, US", "New York, US", "England, GB"],
            "city": ["San Francisco", "New York", "London", "Toronto", "Berlin"],
        }

    def _get_api_url(self, project_id: int, path: str) -> str:
        return f"{get_api_host()}/api/projects/{project_id}/external_web_analytics/{path}"

    def generate_overview_data(self, request_data: dict[str, Any]) -> dict[str, Any]:
        base_visitors = random.randint(5000, 50000)
        base_views = int(base_visitors * random.uniform(1.2, 4.0))
        base_sessions = int(base_visitors * random.uniform(0.7, 1.1))
        bounce_rate = random.uniform(0.3, 0.8)
        session_duration = random.uniform(60, 420)

        data = {
            "visitors": base_visitors,
            "views": base_views,
            "sessions": base_sessions,
            "bounce_rate": round(bounce_rate, 3),
            "session_duration": round(session_duration, 1),
        }

        serializer = WebAnalyticsOverviewResponseSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def generate_trends_data(self, request_data: dict[str, Any], team_id: int) -> dict[str, Any]:
        date_from = request_data["date_from"]
        date_to = request_data["date_to"]

        if isinstance(date_from, str):
            date_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        if isinstance(date_to, str):
            date_to = datetime.strptime(date_to, "%Y-%m-%d").date()

        interval = request_data.get("interval", "day")
        metric = request_data["metric"]
        limit = request_data.get("limit", 100)
        offset = request_data.get("offset", 0)

        # Generate all data points first
        all_data_points = []
        current_date = date_from

        while current_date <= date_to:
            # Simulate weekly patterns (lower on weekends)
            weekday_factor = 0.7 if current_date.weekday() >= 5 else 1.0
            base_value = self._get_metric_value(metric, weekday_factor)

            point_data = {
                "datetime": current_date.isoformat() + "T00:00:00Z",
                "value": base_value,
            }

            # Validate each data point
            point_serializer = WebAnalyticsTrendPointSerializer(data=point_data)
            point_serializer.is_valid(raise_exception=True)
            all_data_points.append(point_serializer.validated_data)

            current_date = self._increment_date(current_date, interval)

        # Apply pagination
        total_count = len(all_data_points)
        paginated_results = all_data_points[offset : offset + limit]

        # Generate dummy pagination URLs
        has_next = offset + limit < total_count
        has_previous = offset > 0

        data = {
            "metric": metric,
            "interval": interval,
            "count": total_count,
            "next": self._get_api_url(team_id, f"trend/?offset={offset + limit}&limit={limit}") if has_next else None,
            "previous": self._get_api_url(team_id, f"trend/?offset={max(0, offset - limit)}&limit={limit}")
            if has_previous
            else None,
            "results": paginated_results,
        }

        serializer = WebAnalyticsTrendResponseSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def generate_breakdown_data(self, request_data: dict[str, Any], team_id: int) -> dict[str, Any]:
        breakdown_by = request_data["breakdown_by"]
        metrics = request_data.get("metrics") or ["visitors", "views", "bounce_rate"]
        limit = request_data.get("limit", 25)
        offset = request_data.get("offset", 0)

        # Get breakdown values for the specified property
        values = self.breakdown_values.get(breakdown_by, [f"{breakdown_by}_{i}" for i in range(1, 50)])

        # Create weighted distribution (top items get more traffic)
        weights = [1.0 / (i + 1) for i in range(len(values))]
        total_weight = sum(weights)

        # Generate all results first
        all_results = []
        for i, value in enumerate(values):
            weight = weights[i] / total_weight

            # Generate metrics for this breakdown item
            item = {"value": value}

            for metric in metrics:
                item[metric] = self._generate_breakdown_metric(metric, weight)

            all_results.append(item)

        # Apply pagination
        total_count = len(all_results)
        paginated_results = all_results[offset : offset + limit]

        # Generate dummy pagination URLs
        has_next = offset + limit < total_count
        has_previous = offset > 0

        data = {
            "breakdown_by": breakdown_by,
            "count": total_count,
            "next": self._get_api_url(team_id, f"breakdown/?offset={offset + limit}&limit={limit}")
            if has_next
            else None,
            "previous": self._get_api_url(team_id, f"breakdown/?offset={max(0, offset - limit)}&limit={limit}")
            if has_previous
            else None,
            "results": paginated_results,
        }

        serializer = WebAnalyticsBreakdownResponseSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _get_metric_value(self, metric: str, weekday_factor: float = 1.0) -> int:
        min_val, max_val = self.metric_ranges.get(metric, (100, 1000))
        value = random.uniform(min_val, max_val) * weekday_factor
        return int(value)

    def _increment_date(self, date, interval: str):
        if interval == "hour":
            return date + timedelta(hours=1)
        elif interval == "day":
            return date + timedelta(days=1)
        elif interval == "week":
            return date + timedelta(weeks=1)
        elif interval == "month":
            return date + timedelta(days=30)
        return date + timedelta(days=1)

    def _generate_breakdown_metric(self, metric: str, weight: float) -> Any:
        if metric == "visitors":
            return int(random.randint(100, 5000) * weight * 10)
        elif metric == "views":
            # Views should be higher than visitors
            base_visitors = int(random.randint(100, 5000) * weight * 10)
            return int(base_visitors * random.uniform(1.2, 3.5))
        elif metric == "sessions":
            # Sessions should be close to visitors
            base_visitors = int(random.randint(100, 5000) * weight * 10)
            return int(base_visitors * random.uniform(0.8, 1.1))
        elif metric == "bounce_rate":
            return round(random.uniform(0.25, 0.85), 3)
        elif metric == "session_duration":
            return round(random.uniform(30, 500), 1)
        elif metric == "conversion_rate":
            return round(random.uniform(0.005, 0.12), 4)
        else:
            return int(random.randint(10, 1000) * weight * 5)
