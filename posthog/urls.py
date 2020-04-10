from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic.base import TemplateView
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.contrib.auth import authenticate, login, views as auth_views, decorators
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import render_to_string

from .api import router, capture, user
from .models import Team, User
from .utils import render_template
from .views import health, stats
from posthog.demo import demo, delete_demo_data
import json
import posthoganalytics
import os

from rest_framework import permissions

def home(request, **kwargs):
    if request.path.endswith('.map') or request.path.endswith('.map.js'):
        return redirect('/static%s' % request.path)
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
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            posthoganalytics.capture(user.distinct_id, 'user logged in')
            return redirect('/')
        else:
            return render_template('login.html', request=request, context={'email': email, 'error': True})
    return render_template('login.html', request)

def signup_to_team_view(request, token):
    if request.user.is_authenticated:
        return redirect('/')
    if not token:
        return redirect('/')
    if not User.objects.exists():
        return redirect('/setup_admin')
    try: 
        team = Team.objects.get(signup_token=token)
    except Team.DoesNotExist:
        return redirect('/')

    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']
        first_name=request.POST.get('name')
        email_opt_in=request.POST.get('emailOptIn')

        if email_opt_in == 'on':
            email_opt_in = True

        try:
            user = User.objects.create_user(email=email, password=password, first_name=first_name, email_opt_in=email_opt_in)
        except:
            return render_template('signup_to_team.html', request=request, context={'email': email, 'error': True, 'team': team, 'signup_token': token})
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        team.users.add(user)
        team.save()
        posthoganalytics.capture(user.distinct_id, 'user signed up', properties={'is_first_user': False})
        posthoganalytics.identify(user.distinct_id, {'email_opt_in': user.email_opt_in})
        return redirect('/')
    return render_template('signup_to_team.html', request, context={'team': team, 'signup_token': token})

def setup_admin(request):
    if User.objects.exists():
        return redirect('/login')
    if request.method == 'GET':
        if request.user.is_authenticated:
            return redirect('/')
        return render_template('setup_admin.html', request)
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']
        company_name = request.POST.get('company_name')
        is_first_user = not User.objects.exists()
        try:
            user = User.objects.create_user(email=email, password=password, first_name=request.POST.get('name'))
        except:
            return render_template('setup_admin.html', request=request, context={'error': True, 'email': request.POST['email'], 'company_name': request.POST.get('company_name'), 'name': request.POST.get('name')})
        Team.objects.create_with_data(users=[user], name=company_name)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        posthoganalytics.capture(user.distinct_id, 'user signed up', properties={'is_first_user': is_first_user})
        posthoganalytics.identify(user.distinct_id, properties={
            'email': user.email,
            'company_name': company_name,
            'name': user.first_name
        })
        return redirect('/')

def social_create_user(strategy, details, backend, user=None, *args, **kwargs):
    if user:
        return {'is_new': False}

    signup_token = strategy.session_get('signup_token')
    if signup_token is None:
        processed = render_to_string('auth_error.html', {'message': "There is no team associated with this account! Please use an invite link from a team to create an account!"})
        return HttpResponse(processed, status=401)

    fields = dict((name, kwargs.get(name, details.get(name)))
                   for name in backend.setting('USER_FIELDS', ['email']))
    
    if not fields:
        return

    try: 
        team = Team.objects.get(signup_token=signup_token)
    except Team.DoesNotExist:
        processed = render_to_string('auth_error.html', {'message': "We can't find the team associated with this signup token. Please ensure the invite link is provided from an existing team!"})
        return HttpResponse(processed, status=401)

    try:
        user = strategy.create_user(**fields)
    except:
        processed = render_to_string('auth_error.html', {'message': "Account unable to be created. This account may already exist. Please try again or use different credentials!"})
        return HttpResponse(processed, status=401)

    team.users.add(user)
    team.save()
    posthoganalytics.capture(user.distinct_id, 'user signed up', properties={'is_first_user': False})

    return {
        'is_new': True,
        'user': user
    }

def logout(request):
    return auth_views.logout_then_login(request)

urlpatterns = [
    path('_health/', health),
    path('_stats/', stats),
    path('admin/', admin.site.urls),
    path('admin/', include('loginas.urls')),
    path('api/', include(router.urls)),

    path('api/user/', user.user),
    path('api/user/redirect_to_site/', user.redirect_to_site),
    path('api/user/change_password/', user.change_password),
    path('api/user/test_slack_webhook/', user.test_slack_webhook),
    path('decide/', capture.get_decide),
    path('engage/', capture.get_event),
    path('engage', capture.get_event),
    re_path(r'^demo.*', decorators.login_required(demo)),
    path('delete_demo_data/', decorators.login_required(delete_demo_data)),
    path('e/', capture.get_event),
    path('track', capture.get_event),
    path('track/', capture.get_event),
    path('capture', capture.get_event),
    path('capture/', capture.get_event),
    path('batch', capture.get_event),
    path('batch/', capture.get_event),
]

if not settings.EMAIL_HOST:
    urlpatterns.append(path('accounts/password_reset/', TemplateView.as_view(template_name='registration/password_no_smtp.html')))

urlpatterns = urlpatterns + [
    # auth
    path('logout', logout, name='login'),
    path('login', login_view, name='login'),
    path('signup/<str:token>', signup_to_team_view, name='signup'),
    path('', include('social_django.urls', namespace='social')),
    path('setup_admin', setup_admin, name='setup_admin'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        success_url='/',
        post_reset_login_backend='django.contrib.auth.backends.ModelBackend',
        post_reset_login=True,
    )),
    path('accounts/', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    @csrf_exempt
    def debug(request):
        assert False, locals()
    urlpatterns += [
        path('debug/', debug)
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

urlpatterns += [
    re_path(r'^.*', decorators.login_required(home)),
]
