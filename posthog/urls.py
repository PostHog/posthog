from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic.base import TemplateView
from django.template.loader import get_template
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.contrib.auth import authenticate, login, views as auth_views, decorators
from django.conf import settings


from .api import router, capture, user
from .models import Team, User
import json
import posthoganalytics

from rest_framework import permissions




def render_template(template_name: str, request, context=None) -> HttpResponse:
    template = get_template(template_name)
    html = template.render(context, request=request)
    return HttpResponse(html.replace('src="/', 'src="/static/').replace('href="/', 'href="/static/'))

def home(request, **kwargs):
    if request.path.endswith('.map'):
        return redirect('/static/%s' % request.path)
    return render_template('index.html', request)

def login_view(request):
    if request.user.is_authenticated:
        return redirect('/')

    if not User.objects.exists():
        return redirect('/setup_admin')
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']
        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
            posthoganalytics.capture(user.distinct_id, 'user logged in')
            return redirect('/')
        else:
            return render_template('login.html', request=request, context={'email': email, 'error': True})
    return render_template('login.html', request)

def signup_view(request):
    if request.method == 'GET':
        if request.user.is_authenticated:
            return redirect('/')
        if not User.objects.exists():
            return redirect('/setup_admin')
        return render_template('signup.html', request)
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']
        company_name = request.POST.get('company_name')
        is_first_user = not User.objects.exists()
        try:
            user = User.objects.create_user(email=email, password=password, first_name=request.POST.get('name'))
        except:
            return render_template('signup.html', request=request, context={'error': True, 'email': request.POST['email'], 'company_name': request.POST.get('company_name'), 'name': request.POST.get('name')})
        team = Team.objects.create(name=company_name)
        team.users.add(user)
        login(request, user)
        posthoganalytics.capture(user.distinct_id, 'user signed up', properties={'is_first_user': is_first_user})
        posthoganalytics.identify(user.distinct_id, properties={
            'email': user.email,
            'company_name': company_name,
            'name': user.first_name
        })
        return redirect('/setup')

def setup_admin(request):
    if User.objects.exists():
        return redirect('/login')
    if request.method == 'GET':
        if request.user.is_authenticated:
            return redirect('/')
        return render_template('signup.html', request)

def logout(request):
    return auth_views.logout_then_login(request)

def demo(request):
    return render_template('demo.html', request=request, context={'api_token': request.user.team_set.get().api_token})

urlpatterns = [
    path('admin/', admin.site.urls),
    path('admin/', include('loginas.urls')),
    path('api/', include(router.urls)),

    path('api/user/', user.user),
    path('api/user/redirect_to_site/', user.redirect_to_site),
    path('decide/', capture.get_decide),
    path('engage/', capture.get_engage),
    path('engage', capture.get_engage),
    re_path(r'demo.*', decorators.login_required(demo)),
    path('e/', capture.get_event),
    path('track', capture.get_event),
    path('track/', capture.get_event),
    path('capture/', capture.get_event),
    path('batch/', capture.batch),
    path('logout', logout, name='login'),
    path('login', login_view, name='login'),
    path('signup', signup_view, name='signup'),
    path('setup_admin', setup_admin, name='setup_admin'),



    # react frontend
    re_path(r'^.*', decorators.login_required(home)),
]


if hasattr(settings, 'INCLUDE_API_DOCS'):
    from drf_yasg.views import get_schema_view
    from drf_yasg import openapi
    schema_view = get_schema_view(
        openapi.Info(
            title="PostHog API",
            default_version='v1',
            description="PostHog's API allows you to do anything you can do in the PostHog frontend.",
            contact=openapi.Contact(email="hey@posthog.com"),
            license=openapi.License(name="MIT License"),
        ),
        public=True,
        permission_classes=(permissions.AllowAny,),
    )
    urlpatterns += [
        re_path(r'^swagger(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
        re_path(r'^swagger/$', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
        re_path(r'^redoc/$', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    ]