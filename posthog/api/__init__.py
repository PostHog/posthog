from . import event, person, action, funnel, dashboard, paths
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'event', event.EventViewSet)
router.register(r'person', person.PersonViewSet)
router.register(r'action', action.ActionViewSet)
router.register(r'funnel', funnel.FunnelViewSet)
router.register(r'dashboard', dashboard.DashboardViewSet)
router.register(r'paths', paths.PathsViewSet, basename='paths')