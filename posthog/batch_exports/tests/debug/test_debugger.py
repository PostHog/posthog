import pytest


from posthog.batch_exports.debug.debugger import BatchExportsDebugger

pytestmark = [
    pytest.mark.django_db,
]


def test_debugger_loads_batch_exports_for_team(team):
    bedbg = BatchExportsDebugger(team.pk)

    assert len(bedbg.loaded_batch_exports) == 2
