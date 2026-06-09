# TEMP — DO NOT MERGE. Validates .github/scripts/run-with-hang-autopsy.sh by
# reproducing the hang's worst case: a native call that never returns and HOLDS
# the GIL (PyDLL skips the GIL release that CDLL does), so no in-process
# watchdog can observe it. The autopsy watchdog must fire at the step bound,
# dump this process's native stacks via py-spy, and fail the step.
import ctypes


def test_wedge_in_native_call_holding_gil() -> None:
    ctypes.PyDLL(None).sleep(7200)
