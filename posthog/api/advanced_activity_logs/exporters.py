import csv
import json
from abc import ABC, abstractmethod

from django.db.models import QuerySet
from django.http import HttpResponse

from posthog.models.activity_logging.activity_log import ActivityLog

EMPTY_VALUE = "(empty)"


class AdvancedActivityLogExporter(ABC):
    def __init__(self, queryset: QuerySet[ActivityLog]):
        self.queryset = queryset

    @abstractmethod
    def export(self) -> HttpResponse:
        """Export the queryset in the specific format."""
        pass

    def _prepare_export_data(self) -> list[dict]:
        logs_data = []
        for log in self.queryset:
            logs_data.append(
                {
                    "id": str(log.id),
                    "organization_id": str(log.organization_id),
                    "project_id": str(log.team_id),
                    "user": {
                        "id": str(log.user.id),
                        "email": log.user.email,
                        "first_name": log.user.first_name,
                        "last_name": log.user.last_name,
                    }
                    if log.user
                    else None,
                    "activity": log.activity,
                    "scope": log.scope,
                    "item_id": log.item_id,
                    "detail": log.detail,
                    "created_at": log.created_at.isoformat(),
                }
            )
        return logs_data


class CSVExporter(AdvancedActivityLogExporter):
    def export(self) -> HttpResponse:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="advanced-activity-logs.csv"'

        writer = csv.writer(response)
        writer.writerow(
            ["Organization ID", "Project ID", "User", "Activity", "Scope", "Item ID", "Detail", "Created At"]
        )

        for log in self.queryset:
            writer.writerow(
                [
                    log.organization_id,
                    log.team_id or EMPTY_VALUE,
                    f"{log.user.first_name} {log.user.last_name}".strip() if log.user else "Posthog",
                    log.activity,
                    log.scope,
                    log.item_id,
                    json.dumps(log.detail) if log.detail else EMPTY_VALUE,
                    log.created_at.isoformat(),
                ]
            )

        return response


class JSONExporter(AdvancedActivityLogExporter):
    def export(self) -> HttpResponse:
        response = HttpResponse(content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="advanced-activity-logs.json"'

        logs_data = self._prepare_export_data()
        response.write(json.dumps(logs_data, indent=2))

        return response


class ExporterFactory:
    EXPORTERS = {
        "csv": CSVExporter,
        "json": JSONExporter,
    }

    @classmethod
    def create_exporter(cls, format_type: str, queryset: QuerySet[ActivityLog]) -> AdvancedActivityLogExporter:
        if format_type not in cls.EXPORTERS:
            raise ValueError(f"Unsupported export format: {format_type}")

        exporter_class = cls.EXPORTERS[format_type]
        return exporter_class(queryset)
