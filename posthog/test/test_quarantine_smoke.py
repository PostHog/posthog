# Throwaway end-to-end validation of the checked-in test quarantine (#62737).
# Both tests fail on purpose: the quarantine file neutralizes them, so CI is
# green only if enforcement works — `run` mode reports xfailed, `skip` mode
# never executes. Delete this file (and its quarantine entries) before merge;
# this PR is not meant to land.


def test_quarantine_run_mode_should_xfail() -> None:
    # Quarantined mode=run -> still executes, marked xfail(strict=False),
    # so this failure is reported as xfailed and cannot fail the shard.
    raise AssertionError("intentional failure neutralized by quarantine mode=run")


def test_quarantine_skip_mode_should_not_run() -> None:
    # Quarantined mode=skip -> never executed. If it ever runs, this fails CI.
    raise AssertionError("intentional failure that quarantine mode=skip must prevent")
