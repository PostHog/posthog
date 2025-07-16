from datetime import datetime, timedelta
import random
from typing import Any

from rest_framework.request import Request

from .serializers import (
    EXTERNAL_WEB_ANALYTICS_PAGINATION_DEFAULT_LIMIT,
    EXTERNAL_WEB_ANALYTICS_SUPPORTED_METRICS,
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

        self.breakdown_values: dict[str, list[str]] = {
            "Page": ["/home", "/products", "/about", "/pricing", "/blog", "/contact", "/features", "/login", "/signup"],
            "InitialPage": ["/home", "/products", "/blog", "/pricing", "/about", "/features"],
            "ExitPage": ["/contact", "/pricing", "/checkout", "/home", "/products"],
            "InitialReferringDomain": ["google.com", "facebook.com", "direct", "twitter.com", "linkedin.com"],
            "InitialUTMSource": ["google", "facebook", "twitter", "linkedin", "email"],
            "InitialUTMCampaign": ["summer_sale", "product_launch", "brand_awareness", "retargeting"],
            "InitialUTMMedium": ["cpc", "organic", "email", "social", "referral"],
            "InitialUTMTerm": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
            "InitialUTMContent": ["banner_top", "banner_side", "text_link", "button_cta", "footer_link"],
            "Viewport": ["1920x1080", "1366x768", "1440x900", "1536x864", "1280x720", "375x667", "414x896"],
            "Browser": ["Chrome", "Safari", "Firefox", "Edge", "Opera"],
            "OS": ["Windows", "macOS", "iOS", "Android", "Linux"],
            "DeviceType": ["Desktop", "Mobile", "Tablet"],
            "Country": ["US", "GB", "CA", "DE", "FR", "AU", "JP", "BR"],
            "Region": ["California, US", "Texas, US", "New York, US", "England, GB"],
            "City": ["San Francisco", "New York", "London", "Toronto", "Berlin"],
        }

    def _get_api_url(self, request: Request, team_id: int, endpoint: str, params: dict) -> str:
        """Build the full API URL for pagination links with all parameters"""
        base_url = request.build_absolute_uri("/")[:-1]  # Remove trailing slash

        # Filter out None values and convert booleans to lowercase strings
        clean_params = {}
        for k, v in params.items():
            if v is not None:
                if isinstance(v, bool):
                    clean_params[k] = str(v).lower()
                elif isinstance(v, list):
                    clean_params[k] = ",".join(str(item) for item in v)
                else:
                    clean_params[k] = str(v)

        query_string = "&".join([f"{k}={v}" for k, v in clean_params.items()])

        return f"{base_url}/api/projects/{team_id}/external_web_analytics/{endpoint}/?{query_string}"

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

    def generate_trends_data(self, request_data: dict[str, Any], request: Request, team_id: int) -> dict[str, Any]:
        date_from = request_data["date_from"]
        date_to = request_data["date_to"]
        domain = request_data["domain"]

        if isinstance(date_from, str):
            date_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        if isinstance(date_to, str):
            date_to = datetime.strptime(date_to, "%Y-%m-%d").date()

        interval = request_data.get("interval", "day")
        metric = request_data["metric"]
        limit = request_data.get("limit", EXTERNAL_WEB_ANALYTICS_PAGINATION_DEFAULT_LIMIT)
        offset = request_data.get("offset", 0)

        # Generate all data points first
        all_data_points = []
        current_date = date_from

        while current_date <= date_to:
            # Simulate weekly patterns (lower on weekends)
            weekday_factor = 0.7 if current_date.weekday() >= 5 else 1.0
            base_value = self._get_metric_value(metric, weekday_factor)

            point_data = {
                "time": current_date.isoformat() + "T00:00:00Z",
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

        base_params = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "domain": domain,
            "interval": interval,
            "metric": metric,
            "limit": limit,
            "offset": offset,
        }

        # Initialize pagination URLs
        next_url = None
        previous_url = None

        if has_next:
            next_params = {**base_params, "offset": offset + limit}
            next_url = self._get_api_url(request, team_id, "trend", next_params)

        if has_previous:
            prev_params = {**base_params, "offset": max(0, offset - limit)}
            previous_url = self._get_api_url(request, team_id, "trend", prev_params)

        data = {
            "count": total_count,
            "next": next_url,
            "previous": previous_url,
            "results": paginated_results,
        }

        serializer = WebAnalyticsTrendResponseSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def generate_breakdown_data(self, request_data: dict[str, Any], request: Request, team_id: int) -> dict[str, Any]:
        date_from = request_data["date_from"]
        date_to = request_data["date_to"]
        breakdown_by = request_data["breakdown_by"]
        metrics = request_data.get("metrics", ",".join(EXTERNAL_WEB_ANALYTICS_SUPPORTED_METRICS))
        limit = request_data.get("limit", EXTERNAL_WEB_ANALYTICS_PAGINATION_DEFAULT_LIMIT)
        offset = request_data.get("offset", 0)
        domain = request_data["domain"]

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

        base_params = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "domain": domain,
            "breakdown_by": breakdown_by,
            "metrics": metrics,
            "limit": limit,
            "offset": offset,
        }

        # Initialize pagination URLs
        next_url = None
        previous_url = None

        if has_next:
            next_params = {**base_params, "offset": offset + limit}
            next_url = self._get_api_url(request, team_id, "breakdown", next_params)
        else:
            next_url = None

        if has_previous:
            prev_params = {**base_params, "offset": max(0, offset - limit)}
            previous_url = self._get_api_url(request, team_id, "breakdown", prev_params)
        else:
            previous_url = None

        data = {
            "count": total_count,
            "next": next_url,
            "previous": previous_url,
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
        if interval == "minute":
            return date + timedelta(minutes=1)
        elif interval == "hour":
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
        else:
            return int(random.randint(10, 1000) * weight * 5)
