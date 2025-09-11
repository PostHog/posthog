from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response


class ForbidDestroyModel:
    @extend_schema(
        responses={
            405: None,
        },
        description='Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true',
    )
    def destroy(self, request, *args, **kwargs) -> Response:
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
