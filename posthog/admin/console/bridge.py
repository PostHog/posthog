from collections.abc import Callable
from typing import Any

from django import forms
from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

AdminView = Callable[[Any, HttpRequest, str], HttpResponse]


class AdminViewBridge:
    """Run an existing Django admin view as a console operation.

    A workflow can move to the console before its logic leaves the `ModelAdmin`. The console owns the
    page and the form; the admin view still does the work. When the logic moves to a service function,
    swap the operation's handler and leave the console page as it is.

    Pass the view as a method reference, for example `TeamAdmin.rebuild_cache`, so a renamed view fails
    on import instead of when staff click the button.

    Only bridge views that take a POST and answer with a redirect. The redirect points into Django admin,
    so the bridge drops it and the console sends staff back to the console page. Messages the view adds
    still show there.
    """

    def __init__(self, model: type[Model], view: AdminView) -> None:
        self.model = model
        self.view = view

    def __call__(self, request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
        model_admin = admin.site.get_model_admin(self.model)
        response = self.view(model_admin, request, str(obj.pk))
        if isinstance(response, HttpResponseRedirect):
            return None
        return response
