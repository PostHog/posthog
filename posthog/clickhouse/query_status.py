from django.dispatch import Signal

from rest_framework.exceptions import NotFound


class QueryNotFoundError(NotFound):
    pass


# A receiver may raise QueryNotFoundError before a stored result is returned to any caller.
validate_completed_query_result = Signal()
