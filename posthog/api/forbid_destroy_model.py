from rest_framework import status
from rest_framework.response import Response


class ForbidDestroyModel:
    """
    Override the default in ModelViewSet that allows callers to destroy a model instance.
    """

    def destroy(self, request, *args, **kwargs) -> Response:
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
