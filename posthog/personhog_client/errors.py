from rest_framework.exceptions import APIException


class PersonLookupTemporarilyUnavailable(APIException):
    # 503 (not the default 500) marks the failure as transient and retryable: the person data
    # store (personhog) is momentarily unreachable, not the request itself being invalid. Clients
    # treat 5xx-transient statuses as "try again" rather than reporting them as unhandled errors.
    status_code = 503
    default_code = "person_lookup_unavailable"
    default_detail = "We couldn't look up this person right now because the person data store is temporarily unavailable. Please try again in a moment."
