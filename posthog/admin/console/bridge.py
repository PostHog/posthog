from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest, HttpResponse


class AdminViewBridge:
    """Run an existing Django admin view as a console operation.

    A workflow can move to the console before its logic leaves the `ModelAdmin`. The console owns the
    page and the form; the admin view still does the work. When the logic moves to a service function,
    swap the operation's handler and leave the console page as it is.

    Only bridge views that take a POST and answer with a redirect. The console ignores the redirect target
    and sends staff back to the console page. Messages the view adds still show.
    """

    def __init__(self, model: type[Model], view_name: str) -> None:
        self.model = model
        self.view_name = view_name

    def __call__(self, request: HttpRequest, obj: Model) -> HttpResponse:
        model_admin = admin.site.get_model_admin(self.model)
        view = getattr(model_admin, self.view_name)
        return view(request, str(obj.pk))
