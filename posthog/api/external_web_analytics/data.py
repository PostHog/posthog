import random
from datetime import datetime, timedelta
from typing import Any

from rest_framework.request import Request

from .serializers import (
    EXTERNAL_WEB_ANALYTICS_PAGINATION_DEFAULT_LIMIT,
    WebAnalyticsTrendPointSerializer,
    WebAnalyticsTrendResponseSerializer,
)


class WebAnalyticsDataFactory:
    def __init__(self):
        self.metric_ranges = {
            "visitors": (500, 3000),
            "views": (800, 8000),
            "sessions": (400, 2500),
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

    def generate_trends_data(self, request_data: dict[str, Any], request: Request, team_id: int) -> dict[str, Any]:
        date_from = request_data["date_from"]
        date_to = request_data["date_to"]
        host = request_data["host"]

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

        base_params = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "host": host,
            "interval": interval,
            "metric": metric,
            "limit": limit,
            "offset": offset,
        }

        # Initialize pagination URL
        next_url = None

        if has_next:
            next_params = {**base_params, "offset": offset + limit}
            next_url = self._get_api_url(request, team_id, "trend", next_params)

        data = {
            "next": next_url,
            "results": paginated_results,
        }

        serializer = WebAnalyticsTrendResponseSerializer(data=data)
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
