from datetime import datetime, timedelta
import random
from typing import Any


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

    def generate_overview_data(self, request_data: dict[str, Any]) -> dict[str, Any]:
        base_visitors = random.randint(5000, 50000)
        base_views = int(base_visitors * random.uniform(1.2, 4.0))
        base_sessions = int(base_visitors * random.uniform(0.7, 1.1))
        bounce_rate = random.uniform(0.3, 0.8)
        session_duration = random.uniform(60, 420)

        return {
            "visitors": base_visitors,
            "views": base_views,
            "sessions": base_sessions,
            "bounce_rate": round(bounce_rate, 3),
            "session_duration": round(session_duration, 1),
        }

    def generate_trends_data(self, request_data: dict[str, Any]) -> dict[str, Any]:
        date_from = datetime.strptime(request_data["date_from"], "%Y-%m-%d").date()
        date_to = datetime.strptime(request_data["date_to"], "%Y-%m-%d").date()
        interval = request_data.get("interval", "day")
        metric = request_data["metric"]

        data_points = []
        comparison_points = []
        current_date = date_from

        # Calculate period length for comparison
        period_length = (date_to - date_from).days + 1
        comparison_start = date_from - timedelta(days=period_length)

        while current_date <= date_to:
            # Simulate weekly patterns (lower on weekends)
            weekday_factor = 0.7 if current_date.weekday() >= 5 else 1.0
            base_value = self._get_metric_value(metric, weekday_factor)

            data_points.append(
                {
                    "date": current_date.isoformat(),
                    "value": base_value,
                }
            )

            # Generate comparison data if requested
            if request_data.get("compare"):
                comparison_date = comparison_start + (current_date - date_from)
                comparison_value = self._get_metric_value(metric, weekday_factor * 0.9)
                comparison_points.append(
                    {
                        "date": comparison_date.isoformat(),
                        "value": comparison_value,
                    }
                )

            current_date = self._increment_date(current_date, interval)

        result = {
            "metric": metric,
            "interval": interval,
            "data": data_points,
        }

        if request_data.get("compare"):
            result["comparison"] = comparison_points

        return result

    def generate_breakdown_data(self, request_data: dict[str, Any]) -> dict[str, Any]:
        breakdown_by = request_data["breakdown_by"]
        metrics = request_data.get("metrics") or ["visitors", "views"]
        limit = request_data.get("limit", 25)

        # Get breakdown values for the specified property
        values = self.breakdown_values.get(breakdown_by, [f"{breakdown_by}_{i}" for i in range(1, 21)])

        # Create weighted distribution (top items get more traffic)
        weights = [1.0 / (i + 1) for i in range(len(values))]
        total_weight = sum(weights)

        results = []
        for i, value in enumerate(values[:limit]):
            weight = weights[i] / total_weight

            # Generate metrics for this breakdown item
            item = {"breakdown_value": value}

            for metric in metrics:
                item[metric] = self._generate_breakdown_metric(metric, weight)

            results.append(item)

        return {
            "breakdown_by": breakdown_by,
            "results": results,
            "has_more": len(values) > limit,
            "total_count": len(values),
        }

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
