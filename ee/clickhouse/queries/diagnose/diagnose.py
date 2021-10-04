from posthog.models import Team
from posthog.models.filters.diagnose_filter import DiagnoseFilter
from posthog.queries.diagnose import DiagnoseResponse


class ClickhouseDiagnose:
    _filter: DiagnoseFilter
    _team: Team

    def __init__(self, filter: DiagnoseFilter, team: Team) -> None:
        pass

    def run(self, *args, **kwargs) -> DiagnoseResponse:
        return {"events": [{"event": "watch video", "value": 1}]}
