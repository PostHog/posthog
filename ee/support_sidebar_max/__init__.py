from posthog.api import projects_router
from .views import MaxViewSet

# Register Max's viewset under the project's router
projects_router.register(r"max", MaxViewSet, "project_max", ["project_id"])
