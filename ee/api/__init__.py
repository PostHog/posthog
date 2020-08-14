from rest_framework import routers

from . import license

router = routers.DefaultRouter()

router.register(r"license", license.LicenseViewSet)
