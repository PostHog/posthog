from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from posthog.models import Team


def inCohort(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    """
    Check if a cohort ID is in a list of cohort IDs.

    Args (from HogQL):
        args[0]: The cohort ID to check for
        args[1]: List of cohort IDs the person belongs to

    Returns:
        True if cohort_id is in the person's cohort list, False otherwise
    """
    if len(args) < 2:
        return False

    cohort_id = args[0]
    person_cohorts = args[1]

    if cohort_id is None or person_cohorts is None:
        return False

    # Ensure person_cohorts is a list or similar collection
    if not isinstance(person_cohorts, list | tuple | set):
        return False

    # Normalize cohort_id - convert to int if numeric, otherwise string
    if isinstance(cohort_id, int | float):
        cohort_id = int(cohort_id)
    else:
        cohort_id = str(cohort_id)

    # Simple membership check with type flexibility
    for cid in person_cohorts:
        if cid is None:
            continue

        # Normalize each cohort ID in the list
        if isinstance(cid, int | float):
            cid = int(cid)
        else:
            cid = str(cid)

        # Direct comparison after normalization
        if cohort_id == cid:
            return True

        # Also check string/int conversion for compatibility
        if isinstance(cohort_id, int) and isinstance(cid, str):
            try:
                if cohort_id == int(cid):
                    return True
            except ValueError:
                pass
        elif isinstance(cohort_id, str) and isinstance(cid, int):
            if cohort_id == str(cid):
                return True

    return False


def notInCohort(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    """
    Check if the current person is NOT in a cohort.

    Args:
        args[0]: The cohort ID to check membership for
        args[1]: List of cohort IDs the person belongs to

    Returns:
        True if args[0] is NOT in the list args[1], False otherwise
    """
    return not inCohort(args, team, stdout, timeout)
