"""Facade for the AEO product.

The only module other products (and core) are allowed to import for data
capabilities. Celery wiring is re-exported from facade/tasks.py.
"""

from __future__ import annotations

import datetime as dt

from posthog.models.team import Team

from products.aeo.backend import gaps
from products.aeo.backend.facade.contracts import CitationGap, CitationRunSummary
from products.aeo.backend.runner import run_citation_checks


def run_citation_checks_for_team(team_id: int) -> CitationRunSummary:
    """Run the team's active prompt set against every configured answer engine
    and record one citation check per prompt x engine."""
    team = Team.objects.get(id=team_id)
    summary, _ = run_citation_checks(team)
    return summary


def list_citation_gaps(team_id: int, *, since: dt.datetime) -> list[CitationGap]:
    return gaps.list_citation_gaps(team_id, since=since)
