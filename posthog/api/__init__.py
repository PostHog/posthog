from . import event, person, action
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'event', event.EventViewSet)
router.register(r'person', person.PersonViewSet)
router.register(r'action', action.ActionViewSet)