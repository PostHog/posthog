from . import event
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'event', event.EventViewSet)