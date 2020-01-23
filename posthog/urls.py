"""funnellab URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import TemplateView
from .api import EventViewSet, get_event, get_decide

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/event/', EventViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('decide/', get_decide),
    path('demo', TemplateView.as_view(template_name='demo.html')),
    path('e/', get_event)
]
