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
from django.contrib.auth import authenticate, login, views as auth_views, decorators


from .api import router, capture
from .models import Team, User
import json

def render_template(template_name: str, request, context=None) -> HttpResponse:
    template = get_template(template_name)
    html = template.render(context, request=request)
    return HttpResponse(html.replace('src="/', 'src="/static/').replace('href="/', 'href="/static/'))

def home(request, **kwargs):
    if request.path.endswith('.map'):
        return redirect('/static/%s' % request.path)
    return render_template('index.html', request)

def user(request):
    if not request.user.is_authenticated:
        return HttpResponse('Unauthorized', status=401)

    team = request.user.team_set.get()

    if request.method == 'PATCH':
        data = json.loads(request.body)
        team.app_url = data['team']['app_url']
        team.save()

    return JsonResponse({
        'id': request.user.pk,
        'name': request.user.first_name or request.user.username,
        'email': request.user.email,
        'team': {
            'app_url': team.app_url,
            'api_token': team.api_token
        }
    })

def login_view(request):
    if request.method == 'GET':
        if request.user.is_authenticated:
            return redirect('/')
        return render_template('login.html', request)
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']
        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
            return redirect('/')
        else:
            return render_template('login.html', request=request, context={'email': email, 'error': True})

def signup_view(request):
    if request.method == 'GET':
        if request.user.is_authenticated:
            return redirect('/')
        return render_template('signup.html', request)
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']
        try:
            user = User.objects.create_user(email=email, password=password)
        except:
            return render_template('signup.html', request=request, context={'error': True})
        team = Team.objects.create()
        team.users.add(user)
        login(request, user)
        return redirect('/setup')

def logout(request):
    return auth_views.logout_then_login(request)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/user/', user),
    path('decide/', capture.get_decide),
    path('engage/', capture.get_engage),
    re_path(r'demo.*', TemplateView.as_view(template_name='demo.html')),
    path('e/', capture.get_event),
    path('logout', logout, name='login'),
    path('login', login_view, name='login'),
    path('signup', signup_view, name='signup'),

    # react frontend
    re_path(r'^.*', decorators.login_required(home)),
]
