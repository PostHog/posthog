from rest_framework import status
from rest_framework import viewsets
from rest_framework.response import Response

from hogql_parser import parse_program
from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql.bytecode import create_bytecode, Local
from posthog.schema import HogCompileResponse


class HogViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    def create(self, request, *args, **kwargs) -> Response:
        hog = request.data.get("hog")
        locals = request.data.get("locals", []) or []
        local_locals = [Local(name=local[0], depth=local[1], is_captured=local[2]) for local in locals]
        program = parse_program(hog)
        compiled = create_bytecode(
            program,
            supported_functions={"fetch", "postHogCapture", "run"},
            keep_last_scope_open=True,
            locals=local_locals,
        )
        return Response(
            HogCompileResponse(
                bytecode=compiled.bytecode,
                locals=[[local.name, local.depth, local.is_captured] for local in compiled.locals],
                upvalues=[],
            ).model_dump(),
            status=status.HTTP_200_OK,
        )
