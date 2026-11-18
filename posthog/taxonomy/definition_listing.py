"""What the event and property definition list endpoints share.

Both endpoints list a hand-written query over a table that every tenant shares, so one slow list
can hold a database connection for as long as the caller waits. Bounding the statement sheds that
load at a point we choose and returns a 503 the caller can retry.
"""

from django.db import router
from django.db.models import Model

from rest_framework import status
from rest_framework.exceptions import APIException

# The app database sets no statement_timeout, so without this a slow list keeps consuming database
# CPU until the gateway gives up at 120s, long after the client stopped waiting for it.
DEFINITION_LIST_STATEMENT_TIMEOUT_MS = 25_000


def definition_read_db_alias(model: type[Model]) -> str:
    # The page fetch is an ORM RawQuerySet, so it follows the read router (see ReplicaRouter's
    # opt-in list). The count query and the statement timeout have to land on that same connection
    # or they describe a different session than the one doing the work. ReplicaRouter matches on
    # the model's class name, so pass the model the page query itself runs through — the
    # enterprise child, wherever EE is available — not its parent.
    return router.db_for_read(model)


class DefinitionListTimedOut(APIException):
    # The taxonomic filter renders a failed list the same way as an empty one, so a generic 5xx
    # here reads to the user as an empty project. A stable code lets the client tell a timed-out
    # list apart from any other server error and offer a retry instead. Each endpoint subclasses
    # this to name its own code and message.
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
