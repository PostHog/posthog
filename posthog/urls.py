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
from django.urls import path, include, re_path
from django.views.generic.base import TemplateView
from django.template.loader import get_template
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect

from .api import router, capture

def home(request, **kwargs):
    template = get_template('index.html')
    if request.path.endswith('.map'):
        return redirect('/static/%s' % request.path)
    html = template.render()
    return HttpResponse(html.replace('src="/', 'src="/static/').replace('href="/', 'href="/static/'))

def user(request):
    if not request.user.is_authenticated:
        return HttpResponse('Unauthorized', status=401)

    return JsonResponse({
        'id': request.user.pk,
        'name': request.user.first_name or request.user.username,
        'email': request.user.email
    })

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/user/', user),
    path('decide/', capture.get_decide),
    path('engage/', capture.get_engage),
    re_path(r'demo.*', TemplateView.as_view(template_name='demo.html')),
    path('e/', capture.get_event),

    # react frontend
    re_path(r'^.*', home),
]
