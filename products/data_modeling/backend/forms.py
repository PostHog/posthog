from itertools import islice
from uuid import UUID

from django import forms

from products.data_modeling.backend.logic.node_suspension_selection import (
    Marker,
    Selection,
    matching_suspension_markers,
)
from products.data_modeling.backend.models.data_modeling_job import DataModelingJobEngine

MAX_SUSPENSION_PREVIEW = 500


class ClearNodeSuspensionsForm(forms.Form):
    engine = forms.ChoiceField(
        choices=[("", "All engines"), *DataModelingJobEngine.choices], required=False, initial="clickhouse"
    )
    reason_contains = forms.CharField(
        label="Error text contains",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "cols": 60}),
        help_text="Case-sensitive. Enter one error text per line to match any of them.",
    )
    team_id = forms.IntegerField(label="Team ID", required=False, min_value=1)
    node_ids = forms.CharField(label="Node IDs", required=False, help_text="Comma-separated UUIDs.")
    saved_query_ids = forms.CharField(label="Saved query IDs", required=False, help_text="Comma-separated UUIDs.")
    suspended_from = forms.DateTimeField(
        required=False, help_text="Inclusive. Use an ISO date and time with a UTC offset."
    )
    suspended_to = forms.DateTimeField(
        required=False, help_text="Exclusive. Use an ISO date and time with a UTC offset."
    )
    by = forms.CharField(
        label="By / note",
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2, "cols": 60}),
        help_text="Optional. Explain why you are clearing these suspensions. Leave empty to use your admin user ID.",
    )

    def _uuid_list(self, field: str) -> list[UUID]:
        try:
            return [UUID(item.strip()) for item in self.cleaned_data[field].split(",") if item.strip()]
        except ValueError:
            raise forms.ValidationError("Enter valid comma-separated UUIDs.")

    def clean_node_ids(self) -> list[UUID]:
        return self._uuid_list("node_ids")

    def clean_saved_query_ids(self) -> list[UUID]:
        return self._uuid_list("saved_query_ids")

    def clean(self) -> dict:
        cleaned = super().clean()
        assert cleaned is not None
        reasons = tuple(line for line in cleaned.get("reason_contains", "").splitlines() if line.strip())
        cleaned["reason_contains"] = reasons
        if not (reasons or cleaned.get("node_ids") or cleaned.get("saved_query_ids")):
            raise forms.ValidationError("Enter error text, node IDs, or saved query IDs to select suspensions.")
        start, end = cleaned.get("suspended_from"), cleaned.get("suspended_to")
        if start and end and start >= end:
            raise forms.ValidationError("Suspended to must be after suspended from.")
        return cleaned

    def matching_markers(self) -> list[Marker]:
        data = self.cleaned_data
        markers = list(
            islice(
                matching_suspension_markers(
                    team_id=data["team_id"],
                    node_ids=data["node_ids"],
                    saved_query_ids=data["saved_query_ids"],
                    selection=Selection(
                        engine=data["engine"] or None,
                        reason_contains=data["reason_contains"],
                        suspended_from=data["suspended_from"],
                        suspended_to=data["suspended_to"],
                    ),
                ),
                MAX_SUSPENSION_PREVIEW + 1,
            )
        )
        if len(markers) > MAX_SUSPENSION_PREVIEW:
            raise forms.ValidationError(
                f"More than {MAX_SUSPENSION_PREVIEW} suspensions match. Add filters and preview again."
            )
        return markers
