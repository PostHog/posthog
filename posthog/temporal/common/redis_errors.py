import redis.exceptions

# getaddrinfo EAI_AGAIN (errno -3): the resolver could not get an answer right now, for example
# during a short cluster DNS outage. It clears when DNS comes back, so a Temporal retry self-heals.
# EAI_NONAME ("Name or service not known") and EAI_NODATA ("No address associated with hostname")
# stay unmatched, because both can mean a host that never resolves — a real misconfiguration that
# must keep reaching error tracking. Mirrors the equivalent Postgres marker in db_errors.py.
_TRANSIENT_REDIS_ERROR_MARKERS = ("Temporary failure in name resolution",)

# Count the raised error toward the limit so cyclic or very long chains stay bounded.
_MAX_CAUSE_CHAIN_DEPTH = 10


def is_transient_redis_error(error: BaseException) -> bool:
    """Check this error and its explicit causes for a transient Redis connectivity failure.

    Only a connect-time ConnectionError/TimeoutError whose message matches a marker above
    qualifies — a refused connection or a bad password is a real defect, not a DNS blip, and
    must keep reaching error tracking. Ignores `__context__`: an unrelated failure inside an
    `except` block must stay reportable.
    """
    for _ in range(_MAX_CAUSE_CHAIN_DEPTH):
        if isinstance(error, redis.exceptions.ConnectionError | redis.exceptions.TimeoutError):
            message = str(error)
            if any(marker in message for marker in _TRANSIENT_REDIS_ERROR_MARKERS):
                return True
        if error.__cause__ is None:
            break
        error = error.__cause__
    return False
