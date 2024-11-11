import structlog
from rest_framework import status
from rest_framework import viewsets
from rest_framework.response import Response

from hogql_parser import parse_program
from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql.bytecode import create_bytecode, Local
from posthog.hogql.errors import ExposedHogQLError
from posthog.schema import HogCompileResponse

logger = structlog.get_logger(__name__)


class HogViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    def create(self, request, *args, **kwargs) -> Response:
        hog = request.data.get("hog")
        program = parse_program(hog)
        in_repl = request.data.get("in_repl", "false") in ("true", "True", True)
        locals = request.data.get("locals", []) or []
        try:
            compiled = create_bytecode(
                program,
                supported_functions={"sleep", "fetch", "postHogCapture", "run"},
                in_repl=in_repl,
                locals=[Local(name=local[0], depth=local[1], is_captured=local[2]) for local in locals],
            )
            cleaned_locals = [[local.name, local.depth, local.is_captured] for local in compiled.locals]
            return Response(
                HogCompileResponse(
                    bytecode=compiled.bytecode,
                    locals=cleaned_locals,
                ).model_dump(),
                status=status.HTTP_200_OK,
            )
        except ExposedHogQLError as e:
            return Response({"error": str(e.message)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Failed to compile hog: {e}", exc_info=True, error=e)
            return Response({"error": "Internal error when compiling hog"}, status=status.HTTP_400_BAD_REQUEST)
