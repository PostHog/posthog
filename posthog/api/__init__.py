from . import event, person
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'event', event.EventViewSet)
router.register(r'person', person.PersonViewSet)