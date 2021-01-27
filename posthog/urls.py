from typing import Any, Callable, Optional, Union, cast
from urllib.parse import urlparse

import posthoganalytics
from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import authenticate, decorators, login
from django.contrib.auth import views as auth_views
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import URLPattern, include, path, re_path, reverse
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.generic.base import TemplateView
from loginas.utils import is_impersonated_session, restore_original_login
from sentry_sdk import capture_exception
from social_core.pipeline.partial import partial
from social_django.strategy import DjangoStrategy

from posthog.api import (
    api_not_found,
    capture,
    dashboard,
    decide,
    organization,
    projects_router,
    router,
    user,
)
from posthog.demo import demo
from posthog.email import is_email_available
from posthog.models.organization import Organization

from .models import OrganizationInvite, Team, User
from .utils import render_template
from .views import health, preflight_check, stats, system_status


def home(request, *args, **kwargs):
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
        next_url = request.GET.get("next")
        if user is not None:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            if user.distinct_id:
                posthoganalytics.capture(user.distinct_id, "user logged in")
            if next_url:
                return redirect(next_url)
            return redirect("/")
        else:
            return render_template(
                "login.html",
                request=request,
                context={
                    "email": email,
                    "error": True,
                    "action": "/login" if not next_url else f"/login?next={next_url}",
                },
            )
    return render_template("login.html", request)


class TeamInviteSurrogate:
    """This reimplements parts of OrganizationInvite that enable compatibility with the old Team.signup_token."""

    def __init__(self, signup_token: str):
        team = Team.objects.select_related("organization").get(signup_token=signup_token)
        self.organization = team.organization

    def validate(*args, **kwargs) -> bool:
        return True

    def use(self, user: Any, *args, **kwargs) -> None:
        user.join(organization=self.organization)


def signup_to_organization_view(request, invite_id):
    if not invite_id:
        return redirect("/")
    if not User.objects.exists():
        return redirect("/preflight")
    try:
        invite: Union[OrganizationInvite, TeamInviteSurrogate] = OrganizationInvite.objects.select_related(
            "organization"
        ).get(id=invite_id)
    except (OrganizationInvite.DoesNotExist, ValidationError):
        try:
            invite = TeamInviteSurrogate(invite_id)
        except Team.DoesNotExist:
            return redirect("/")

    organization = cast(Organization, invite.organization)
    user = request.user
    if request.method == "POST":
        if request.user.is_authenticated:
            user = cast(User, request.user)
            try:
                invite.use(user)
            except ValueError as e:
                return render_template(
                    "signup_to_organization.html",
                    request=request,
                    context={
                        "user": user,
                        "custom_error": str(e),
                        "organization": organization,
                        "invite_id": invite_id,
                    },
                )
            else:
                posthoganalytics.capture(
                    user.distinct_id, "user joined from invite", properties={"organization_id": organization.id},
                )
                return redirect("/")
        else:
            email = request.POST["email"]
            password = request.POST["password"]
            first_name = request.POST.get("name")
            email_opt_in = request.POST.get("emailOptIn") == "on"
            valid_inputs = (
                is_input_valid("name", first_name)
                and is_input_valid("email", email)
                and is_input_valid("password", password)
            )
            already_exists = User.objects.filter(email=email).exists()
            custom_error = None
            try:
                invite.validate(user=None, email=email)
            except ValueError as e:
                custom_error = str(e)
            if already_exists or not valid_inputs or custom_error:
                return render_template(
                    "signup_to_organization.html",
                    request=request,
                    context={
                        "email": email,
                        "name": first_name,
                        "already_exists": already_exists,
                        "custom_error": custom_error,
                        "invalid_input": not valid_inputs,
                        "organization": organization,
                        "invite_id": invite_id,
                    },
                )
            user = User.objects.create_user(email, password, first_name=first_name, email_opt_in=email_opt_in)
            invite.use(user, prevalidated=True)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            posthoganalytics.capture(
                user.distinct_id, "user signed up", properties={"is_first_user": False, "first_team_user": False},
            )
            return redirect("/")
    return render_template(
        "signup_to_organization.html",
        request,
        context={"organization": organization, "user": user, "invite_id": invite_id},
    )


class CompanyNameForm(forms.Form):
    companyName = forms.CharField(max_length=64)
    emailOptIn = forms.BooleanField(required=False)


def finish_social_signup(request):
    if request.method == "POST":
        form = CompanyNameForm(request.POST)
        if form.is_valid():
            request.session["company_name"] = form.cleaned_data["companyName"]
            request.session["email_opt_in"] = bool(form.cleaned_data["emailOptIn"])
            return redirect(reverse("social:complete", args=[request.session["backend"]]))
    else:
        form = CompanyNameForm()
    return render(request, "signup_to_organization_company.html", {"user_name": request.session["user_name"]})


@partial
def social_create_user(strategy: DjangoStrategy, details, backend, user=None, *args, **kwargs):
    if user:
        return {"is_new": False}
    user_email = details["email"][0] if isinstance(details["email"], (list, tuple)) else details["email"]
    user_name = details["fullname"]
    strategy.session_set("user_name", user_name)
    strategy.session_set("backend", backend.name)
    from_invite = False
    invite_id = strategy.session_get("invite_id")
    if not invite_id:
        company_name = strategy.session_get("company_name", None)
        email_opt_in = strategy.session_get("email_opt_in", None)
        if not company_name or email_opt_in is None:
            return redirect(finish_social_signup)
        _, _, user = User.objects.bootstrap(
            company_name=company_name, first_name=user_name, email=user_email, email_opt_in=email_opt_in, password=None
        )
    else:
        from_invite = True
        try:
            invite: Union[OrganizationInvite, TeamInviteSurrogate] = OrganizationInvite.objects.select_related(
                "organization"
            ).get(id=invite_id)
        except (OrganizationInvite.DoesNotExist, ValidationError):
            try:
                invite = TeamInviteSurrogate(invite_id)
            except Team.DoesNotExist:
                processed = render_to_string("auth_error.html", {"message": "Invalid invite link!"},)
                return HttpResponse(processed, status=401)

        try:
            invite.validate(user=None, email=user_email)
        except ValueError as e:
            processed = render_to_string("auth_error.html", {"message": str(e)},)
            return HttpResponse(processed, status=401)

        try:
            user = strategy.create_user(email=user_email, first_name=user_name, password=None)
        except Exception as e:
            capture_exception(e)
            processed = render_to_string(
                "auth_error.html",
                {
                    "message": "Account unable to be created. This account may already exist. Please try again or use different credentials!"
                },
            )
            return HttpResponse(processed, status=401)
        invite.use(user, prevalidated=True)

    posthoganalytics.capture(
        user.distinct_id,
        "user signed up",
        properties={
            "is_first_user": User.objects.count() == 1,
            "is_first_team_user": not from_invite,
            "login_provider": backend.name,
        },
    )

    return {"is_new": True, "user": user}


@csrf_protect
def logout(request):
    if request.user.is_authenticated:
        request.user.temporary_token = None
        request.user.save()

    if is_impersonated_session(request):
        restore_original_login(request)
        return redirect("/")

    restore_original_login(request)
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
    extend_api_router(router, projects_router=projects_router)


def opt_slash_path(route: str, view: Callable, name: Optional[str] = None) -> URLPattern:
    """Catches path with or without trailing slash, taking into account query param and hash."""
    # Ignoring the type because while name can be optional on re_path, mypy doesn't agree
    return re_path(fr"^{route}/?(?:[?#].*)?$", view, name=name)  # type: ignore


urlpatterns = [
    # internals
    opt_slash_path("_health", health),
    opt_slash_path("_stats", stats),
    opt_slash_path("_preflight", preflight_check),
    opt_slash_path("_system_status", system_status),
    # admin
    path("admin/", admin.site.urls),
    path("admin/", include("loginas.urls")),
    # api
    path("api/", include(router.urls)),
    opt_slash_path("api/user/redirect_to_site", user.redirect_to_site),
    opt_slash_path("api/user/change_password", user.change_password),
    opt_slash_path("api/user/test_slack_webhook", user.test_slack_webhook),
    opt_slash_path("api/user", user.user),
    opt_slash_path("api/signup", organization.OrganizationSignupViewset.as_view()),
    re_path(r"^api.+", api_not_found),
    path("authorize_and_redirect/", decorators.login_required(authorize_and_redirect)),
    path("shared_dashboard/<str:share_token>", dashboard.shared_dashboard),
    re_path(r"^demo.*", decorators.login_required(demo)),
    # ingestion
    opt_slash_path("decide", decide.get_decide),
    opt_slash_path("e", capture.get_event),
    opt_slash_path("engage", capture.get_event),
    opt_slash_path("track", capture.get_event),
    opt_slash_path("capture", capture.get_event),
    opt_slash_path("batch", capture.get_event),
    opt_slash_path("s", capture.get_event),  # session recordings
    # auth
    path("logout", logout, name="login"),
    path("login", login_view, name="login"),
    path("signup/finish/", finish_social_signup, name="signup_finish"),
    path("signup/<str:invite_id>", signup_to_organization_view, name="signup"),
    path("", include("social_django.urls", namespace="social")),
    *(
        []
        if is_email_available()
        else [
            path("accounts/password_reset/", TemplateView.as_view(template_name="registration/password_no_smtp.html"),)
        ]
    ),
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
    except ImportError:
        pass
    else:
        urlpatterns.append(path("__debug__/", include(debug_toolbar.urls)))

    @csrf_exempt
    def debug(request):
        assert False, locals()

    urlpatterns.append(path("debug/", debug))

# Routes added individually to remove login requirement
frontend_unauthenticated_routes = ["preflight", "signup"]
for route in frontend_unauthenticated_routes:
    urlpatterns.append(path(route, home))

urlpatterns += [
    re_path(r"^.*", decorators.login_required(home)),
]
