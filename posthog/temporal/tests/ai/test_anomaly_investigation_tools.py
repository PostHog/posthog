"""Tests for the live debugger tools in InvestigationToolkit."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from posthog.models import Team
from posthog.temporal.ai.anomaly_investigation.tools import (
    GetLiveDebuggerEventsArgs,
    InstallLiveDebuggerProgramArgs,
    InvestigationToolkit,
    UninstallLiveDebuggerProgramArgs,
)
from products.live_debugger.backend.models import LiveDebuggerProgram


@pytest.mark.django_db(transaction=True)
class TestLiveDebuggerTools:
    @pytest.mark.asyncio
    async def test_install_creates_program_and_returns_id(self, team):
        toolkit = InvestigationToolkit(team=team)
        result = json.loads(
            await toolkit.install_live_debugger_program(
                InstallLiveDebuggerProgramArgs(code="trace foo() {}", description="Test probe")
            )
        )

        assert "program_id" in result
        assert result["status"] == LiveDebuggerProgram.Status.INSTALLED
        program = await LiveDebuggerProgram.objects.aget(id=result["program_id"])
        assert program.team_id == team.id
        assert program.code == "trace foo() {}"
        assert program.description == "Test probe"

    @pytest.mark.asyncio
    async def test_install_is_team_scoped(self, team):
        toolkit = InvestigationToolkit(team=team)
        result = json.loads(
            await toolkit.install_live_debugger_program(
                InstallLiveDebuggerProgramArgs(code="x", description="")
            )
        )
        program = await LiveDebuggerProgram.objects.aget(id=result["program_id"])
        assert program.team_id == team.id

    @pytest.mark.asyncio
    async def test_get_events_returns_json_with_event_count(self, team):
        program = await LiveDebuggerProgram.objects.acreate(team=team, code="x", description="")
        fake_events = [
            MagicMock(
                to_json=MagicMock(
                    return_value={
                        "id": f"evt-{i}",
                        "timestamp": "2026-01-01T00:00:00",
                        "program_id": str(program.id),
                        "probe_id": None,
                        "line_number": 10,
                        "filename": "app.py",
                        "function_name": "handle",
                        "locals": {},
                        "stack_trace": [],
                    }
                )
            )
            for i in range(3)
        ]

        toolkit = InvestigationToolkit(team=team)
        with patch(
            "products.live_debugger.backend.models.LiveDebuggerProgram.get_program_events",
            return_value=fake_events,
        ):
            result = json.loads(
                await toolkit.get_live_debugger_events(
                    GetLiveDebuggerEventsArgs(program_id=str(program.id), limit=10)
                )
            )

        assert result["event_count"] == 3
        assert len(result["events"]) == 3

    @pytest.mark.asyncio
    async def test_get_events_empty_when_none_fired(self, team):
        program = await LiveDebuggerProgram.objects.acreate(team=team, code="x", description="")
        toolkit = InvestigationToolkit(team=team)
        with patch(
            "products.live_debugger.backend.models.LiveDebuggerProgram.get_program_events",
            return_value=[],
        ):
            result = json.loads(
                await toolkit.get_live_debugger_events(
                    GetLiveDebuggerEventsArgs(program_id=str(program.id))
                )
            )

        assert result["event_count"] == 0
        assert result["events"] == []

    @pytest.mark.asyncio
    async def test_uninstall_transitions_status(self, team):
        program = await LiveDebuggerProgram.objects.acreate(team=team, code="x", description="")
        toolkit = InvestigationToolkit(team=team)

        result = json.loads(
            await toolkit.uninstall_live_debugger_program(
                UninstallLiveDebuggerProgramArgs(program_id=str(program.id))
            )
        )

        assert result["ok"] is True
        await program.arefresh_from_db()
        assert program.status == LiveDebuggerProgram.Status.UNINSTALLED

    @pytest.mark.asyncio
    async def test_uninstall_is_idempotent(self, team):
        program = await LiveDebuggerProgram.objects.acreate(
            team=team, code="x", description="", status=LiveDebuggerProgram.Status.UNINSTALLED
        )
        toolkit = InvestigationToolkit(team=team)

        result = json.loads(
            await toolkit.uninstall_live_debugger_program(
                UninstallLiveDebuggerProgramArgs(program_id=str(program.id))
            )
        )

        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_uninstall_ignores_other_team_program(self, team):
        org = await sync_to_async(lambda: team.organization)()
        other_team = await Team.objects.acreate(organization=org, name="OtherTeam")
        program = await LiveDebuggerProgram.objects.acreate(team=other_team, code="x", description="")
        toolkit = InvestigationToolkit(team=team)

        result = json.loads(
            await toolkit.uninstall_live_debugger_program(
                UninstallLiveDebuggerProgramArgs(program_id=str(program.id))
            )
        )

        assert result["ok"] is False
        await program.arefresh_from_db()
        assert program.status == LiveDebuggerProgram.Status.INSTALLED
