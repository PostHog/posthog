import json
import os
from typing import Optional, cast
from urllib.parse import urlparse

import posthoganalytics
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import authenticate, decorators, login
from django.contrib.auth import views as auth_views
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.exceptions import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.urls import include, path, re_path
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.generic.base import TemplateView
from rest_framework import permissions

from posthog.demo import delete_demo_data, demo

from .api import api_not_found, capture, dashboard, decide, router, user
from .models import Event, Team, User
from .utils import render_template
from .views import health, preflight_check, stats


def home(request, **kwargs):
    if request.path.endswith(".map") or request.path.endswith(".map.js"):
        return redirect("/static%s" % request.path)
    return render_template("index.html", request)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("/")

    if not User.objects.exists():
        return redirect("/preflight")
    if request.method == "POST":
        email = request.POST["email"]
        password = request.POST["password"]
        user = cast(Optional[User], authenticate(request, email=email, password=password))
        if user is not None:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            if user.distinct_id:
                posthoganalytics.capture(user.distinct_id, "user logged in")
            return redirect("/")
        else:
            return render_template("login.html", request=request, context={"email": email, "error": True})
    return render_template("login.html", request)


def signup_to_team_view(request, token):
    if request.user.is_authenticated:
        return redirect("/")
    if not token:
        return redirect("/")
    if not User.objects.exists():
        return redirect("/preflight")
    try:
        team = Team.objects.get(signup_token=token)
    except Team.DoesNotExist:
        return redirect("/")

    if request.method == "POST":
        email = request.POST["email"]
        password = request.POST["password"]
        first_name = request.POST.get("name")
        email_opt_in = request.POST.get("emailOptIn") == "on"
        valid_inputs = (
            is_input_valid("name", first_name)
            and is_input_valid("email", email)
            and is_input_valid("password", password)
        )
        email_exists = User.objects.filter(email=email).exists()
        if email_exists or not valid_inputs:
            return render_template(
                "signup_to_team.html",
                request=request,
                context={
                    "email": email,
                    "name": first_name,
                    "error": email_exists,
                    "invalid_input": not valid_inputs,
                    "team": team,
                    "signup_token": token,
                },
            )
        user = User.objects.create_user(
            email=email, password=password, first_name=first_name, email_opt_in=email_opt_in,
        )
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        team.users.add(user)
        team.save()
        posthoganalytics.capture(
            user.distinct_id, "user signed up", properties={"is_first_user": False, "first_team_user": False},
        )
        posthoganalytics.identify(
            user.distinct_id,
            {
                "email": request.user.email if not request.user.anonymize_data else None,
                "company_name": team.name,
                "team_id": team.pk,  # TO-DO: handle multiple teams
                "is_team_first_user": False,
            },
        )
        return redirect("/")
    return render_template("signup_to_team.html", request, context={"team": team, "signup_token": token})


def setup_admin(request):
    if User.objects.exists():
        return redirect("/login")
    if request.method == "GET":
        if request.user.is_authenticated:
            return redirect("/")
        try:
            return render_template("setup_admin.html", request)
        except TemplateDoesNotExist:
            return HttpResponse(
                "Frontend not built yet. Please try again shortly or build manually using <code>./bin/start-frontend</code>"
            )
    if request.method == "POST":
        email = request.POST["email"]
        password = request.POST["password"]
        company_name = request.POST.get("company_name")
        name = request.POST.get("name")
        email_opt_in = request.POST.get("emailOptIn") == "on"
        valid_inputs = (
            is_input_valid("name", name)
            and is_input_valid("email", email)
            and is_input_valid("password", password)
            and is_input_valid("company", company_name)
        )
        if not valid_inputs:
            return render_template(
                "setup_admin.html",
                request=request,
                context={"email": email, "name": name, "invalid_input": True, "company": company_name},
            )
        user = User.objects.create_user(email=email, password=password, first_name=name, email_opt_in=email_opt_in,)
        team = Team.objects.create_with_data(users=[user], name=company_name)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        posthoganalytics.capture(
            user.distinct_id, "user signed up", properties={"is_first_user": True, "first_team_user": True},
        )
        posthoganalytics.identify(
            user.distinct_id,
            properties={
                "email": user.email,
                "company_name": company_name,
                "team_id": team.pk,  # TO-DO: handle multiple teams
                "is_team_first_user": True,
            },
        )
        return redirect("/")


def social_create_user(strategy, details, backend, user=None, *args, **kwargs):
    if user:
        return {"is_new": False}

    signup_token = strategy.session_get("signup_token")
    if signup_token is None:
        processed = render_to_string(
            "auth_error.html",
            {
                "message": "There is no team associated with this account! Please use an invite link from a team to create an account!"
            },
        )
        return HttpResponse(processed, status=401)

    fields = dict((name, kwargs.get(name, details.get(name))) for name in backend.setting("USER_FIELDS", ["email"]))

    if not fields:
        return

    try:
        team = Team.objects.get(signup_token=signup_token)
    except Team.DoesNotExist:
        processed = render_to_string(
            "auth_error.html",
            {
                "message": "We can't find the team associated with this signup token. Please ensure the invite link is provided from an existing team!"
            },
        )
        return HttpResponse(processed, status=401)

    try:
        user = strategy.create_user(**fields)
    except:
        processed = render_to_string(
            "auth_error.html",
            {
                "message": "Account unable to be created. This account may already exist. Please try again or use different credentials!"
            },
        )
        return HttpResponse(processed, status=401)

    team.users.add(user)
    team.save()
    posthoganalytics.capture(
        user.distinct_id, "user signed up", properties={"is_first_user": False, "is_first_team_user": False}
    )

    return {"is_new": True, "user": user}


@csrf_protect
def logout(request):
    if request.user.is_authenticated:
        request.user.temporary_token = None
        request.user.save()

    response = auth_views.logout_then_login(request)
    response.delete_cookie(settings.TOOLBAR_COOKIE_NAME, "/")

    return response


def authorize_and_redirect(request):
    if not request.GET.get("redirect"):
        return HttpResponse("You need to pass a url to ?redirect=", status=401)
    url = request.GET["redirect"]
    return render_template(
        "authorize_and_redirect.html",
        request=request,
        context={"domain": urlparse(url).hostname, "redirect_url": url,},
    )


def is_input_valid(inp_type, val):
    # Uses inp_type instead of is_email for explicitness in function call
    if inp_type == "email":
        return len(val) > 2 and val.count("@") > 0
    return len(val) > 0


# Try to include EE endpoints
try:
    from ee.urls import extend_api_router
except ImportError:
    pass
else:
    extend_api_router(router)


urlpatterns = [
    path("_health/", health),
    path("_stats/", stats),
    path("_preflight/", preflight_check),
    path("admin/", admin.site.urls),
    path("admin/", include("loginas.urls")),
    path("api/", include(router.urls)),
    path("api/user/", user.user),
    path("api/user/redirect_to_site/", user.redirect_to_site),
    path("api/user/change_password/", user.change_password),
    path("api/user/test_slack_webhook/", user.test_slack_webhook),
    re_path(r"api/.+", api_not_found),
    path("authorize_and_redirect/", decorators.login_required(authorize_and_redirect)),
    path("shared_dashboard/<str:share_token>", dashboard.shared_dashboard),
    re_path(r"^demo.*", decorators.login_required(demo)),
    path("delete_demo_data/", decorators.login_required(delete_demo_data)),
    re_path(r"decide/?", decide.get_decide),
    re_path(r"e/?", capture.get_event),
    re_path(r"engage/?", capture.get_event),
    re_path(r"track/?", capture.get_event),
    re_path(r"capture/?", capture.get_event),
    re_path(r"batch/?", capture.get_event),
]

if not settings.EMAIL_HOST:
    urlpatterns.append(
        path("accounts/password_reset/", TemplateView.as_view(template_name="registration/password_no_smtp.html"),)
    )

urlpatterns = urlpatterns + [
    # auth
    path("logout", logout, name="login"),
    path("login", login_view, name="login"),
    path("signup/<str:token>", signup_to_team_view, name="signup"),
    path("", include("social_django.urls", namespace="social")),
    path("setup_admin", setup_admin, name="setup_admin"),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            success_url="/",
            post_reset_login_backend="django.contrib.auth.backends.ModelBackend",
            post_reset_login=True,
        ),
    ),
    path("accounts/", include("django.contrib.auth.urls")),
]

if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns += [
            path("__debug__/", include(debug_toolbar.urls)),
        ]
    except ImportError:
        pass

    @csrf_exempt
    def debug(request):
        assert False, locals()

    urlpatterns += [
        path("debug/", debug),
    ]


urlpatterns += [
    path("preflight", home),  # Added individually to remove login requirement
    re_path(r"^.*", decorators.login_required(home)),
]
