"""What the event and property definition list endpoints share.

Both endpoints list a hand-written query over a table that every tenant shares, so one slow list
can hold a database connection for as long as the caller waits. Bounding the statement sheds that
load at a point we choose and returns a 503 the caller can retry.
"""

from django.db import router
from django.db.models import Field, Model

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


def definition_list_select_column(field: Field, definition_model: type[Model], metadata_table: str) -> str:
    """The select expression that fills `field` on a row of a definition list.

    The list hydrates the enterprise model, which adds fields to `definition_model`. The list reads
    those fields from `metadata_table`, which has a column of the same name for each of them.
    """
    definition_table = definition_model._meta.db_table
    # Qualified by table, so a column name both joined tables carry stays unambiguous.
    if field.model is definition_model:
        return f'{definition_table}."{field.column}"'
    # The metadata table names the primary key of the enterprise model differently. The definition id
    # fills it, so a row without a metadata row still has a primary key.
    if field.primary_key:
        return f'{definition_table}."id" AS "{field.column}"'
    return f'{metadata_table}."{field.column}"'


class DefinitionListTimedOut(APIException):
    # The taxonomic filter renders a failed list the same way as an empty one, so a generic 5xx
    # here reads to the user as an empty project. A stable code lets the client tell a timed-out
    # list apart from any other server error and offer a retry instead. Each endpoint subclasses
    # this to name its own code and message.
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
