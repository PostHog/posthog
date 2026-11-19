# Test cases for facade-views-read-object-not-dangerously-get-object.
# ruff: noqa


class ExportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # ruleid: facade-views-read-object-not-dangerously-get-object
    def dangerously_get_object(self) -> ExportRecord:
        export = get_export(self.team_id, self.kwargs["pk"])
        self.check_object_permissions(self.request, export)
        return export


class RunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    records_have_object_access_rules = False

    # ok: facade-views-read-object-not-dangerously-get-object
    def read_object(self) -> RunRecord | None:
        return get_run(self.team_id, self.kwargs["pk"])
