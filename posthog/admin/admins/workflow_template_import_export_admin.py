import json

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.test import RequestFactory
from django.urls import reverse

from rest_framework.request import Request

from posthog.api.hog_flow_template import HogFlowTemplateSerializer
from posthog.models.hog_flow.hog_flow_template import HogFlowTemplate
from posthog.models.team import Team


class WorkflowTemplateExportForm(forms.Form):
    template_ids = forms.ModelMultipleChoiceField(
        queryset=HogFlowTemplate.objects.none(),  # Will be set in __init__
        required=True,
        help_text="Select one or more global templates to export",
        label="Templates to Export",
        widget=forms.SelectMultiple(attrs={"size": "10"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set queryset after form initialization to only show global templates
        self.fields["template_ids"].queryset = HogFlowTemplate.objects.filter(
            scope=HogFlowTemplate.Scope.GLOBAL
        ).order_by("-updated_at")


class WorkflowTemplateImportForm(forms.Form):
    json_file = forms.FileField(
        required=True,
        help_text="Upload a JSON file containing global workflow template(s) to import (only global templates are allowed)",
        label="JSON File",
    )


def _get_team_id_from_domain(request: HttpRequest) -> int:
    """Auto-detect posthog team ID based on domain"""
    hostname = request.get_host().split(":")[0]
    if hostname == "us.posthog.com":
        return 2
    elif hostname == "eu.posthog.com":
        return 1
    elif hostname == "dev.posthog.dev":
        return 2
    elif hostname == "localhost" or hostname.startswith("127.0.0.1") or hostname.startswith("0.0.0.0"):
        return 1
    else:
        raise ValueError(
            f"Unknown domain '{hostname}'. Cannot auto-detect team ID. Expected us.posthog.com, eu.posthog.com, dev.posthog.dev, or localhost."
        )


def _handle_template_import(request: HttpRequest, import_form: WorkflowTemplateImportForm) -> HttpResponse:
    """Handle template import logic"""
    json_file = import_form.cleaned_data["json_file"]
    try:
        team_id = _get_team_id_from_domain(request)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect(reverse("workflow-template-import-export"))

    try:
        # Parse JSON file
        file_content = json_file.read().decode("utf-8")
        import_data = json.loads(file_content)

        # Ensure it's a list
        if not isinstance(import_data, list):
            import_data = [import_data]

        imported_count = 0
        updated_count = 0
        filtered_ids = []
        errors = []

        # Filter out non-global templates
        global_templates = []
        for template_data in import_data:
            template_scope = template_data.get("scope")
            if template_scope != HogFlowTemplate.Scope.GLOBAL:
                template_id = template_data.get("id")
                if template_id:
                    filtered_ids.append(str(template_id))
            else:
                global_templates.append(template_data)

        if filtered_ids:
            messages.warning(
                request,
                f"{len(filtered_ids)} template(s) will not be imported because they are not official: {', '.join(filtered_ids)}",
            )

        # Validate team_id exists and get team object
        team_exists = True
        team = None
        serializer_context = None
        try:
            team = Team.objects.get(id=team_id)

            # Create a mock DRF request for serializer context
            factory = RequestFactory()
            django_request = factory.post("/")
            django_request.user = request.user
            drf_request = Request(django_request)

            # Create serializer context with get_team function
            def get_team_func():
                return team

            serializer_context = {
                "request": drf_request,
                "team_id": team_id,
                "get_team": get_team_func,
                "created_by": request.user,  # Set to the user doing the import
            }
        except Team.DoesNotExist:
            errors.append(f"Team with ID {team_id} does not exist")
            team_exists = False

        # Real import: use transaction
        if team_exists:
            with transaction.atomic():
                for template_data in global_templates:
                    try:
                        template_id = template_data.get("id")

                        template_scope = template_data.get("scope")
                        if template_scope != HogFlowTemplate.Scope.GLOBAL:
                            errors.append(
                                f"Template '{template_data.get('name', 'Unknown')}' must have global scope, got: {template_scope}"
                            )
                            continue

                        existing_template = None
                        if template_id:
                            try:
                                existing_template = HogFlowTemplate.objects.get(
                                    id=template_id, scope=HogFlowTemplate.Scope.GLOBAL
                                )
                            except HogFlowTemplate.DoesNotExist:
                                pass

                        if existing_template:
                            # Overwrite existing templates
                            serializer = HogFlowTemplateSerializer(
                                instance=existing_template,
                                data=template_data,
                                context=serializer_context,
                                partial=True,
                            )
                            if serializer.is_valid():
                                serializer.save()
                                updated_count += 1
                            else:
                                error_msgs = []
                                for field, field_errors in serializer.errors.items():
                                    if isinstance(field_errors, list):
                                        error_msgs.append(f"{field}: {', '.join(str(e) for e in field_errors)}")
                                    else:
                                        error_msgs.append(f"{field}: {field_errors}")
                                errors.append(
                                    f"Template '{template_data.get('name', 'Unknown')}' (ID: {template_id}) validation failed: {', '.join(error_msgs)}"
                                )
                        else:
                            # Pass template_id in context so serializer can preserve it
                            serializer_context_with_id = {
                                **serializer_context,
                                "template_id": template_id,
                            }
                            serializer = HogFlowTemplateSerializer(
                                data=template_data,
                                context=serializer_context_with_id,
                            )
                            if serializer.is_valid():
                                serializer.save()
                                imported_count += 1
                            else:
                                error_msgs = []
                                for field, field_errors in serializer.errors.items():
                                    if isinstance(field_errors, list):
                                        error_msgs.append(f"{field}: {', '.join(str(e) for e in field_errors)}")
                                    else:
                                        error_msgs.append(f"{field}: {field_errors}")
                                errors.append(
                                    f"Template '{template_data.get('name', 'Unknown')}' validation failed: {', '.join(error_msgs)}"
                                )

                    except Exception as e:
                        errors.append(f"Error processing template '{template_data.get('name', 'Unknown')}': {str(e)}")

        if imported_count > 0:
            messages.success(request, f"Successfully imported {imported_count} template(s)")
        if updated_count > 0:
            messages.success(request, f"Successfully updated {updated_count} template(s)")
        if errors:
            for error in errors:
                messages.error(request, error)

    except json.JSONDecodeError:
        messages.error(request, "Invalid JSON file. Please check the file format.")
    except Exception as e:
        messages.error(request, f"Failed to import templates: {str(e)}")

    return redirect(reverse("workflow-template-import-export"))


def _handle_template_export(request: HttpRequest, export_form: WorkflowTemplateExportForm) -> HttpResponse:
    """Handle template export logic"""
    templates = export_form.cleaned_data["template_ids"]

    export_data = []
    for template in templates:
        serializer = HogFlowTemplateSerializer(template)
        template_dict = serializer.data

        # Add team_id (not included in serializer fields) and ensure id is a string
        template_dict["team_id"] = template.team_id
        template_dict["id"] = str(template_dict["id"])

        template_dict.pop("created_by", None)

        export_data.append(template_dict)

    response = HttpResponse(
        json.dumps(export_data, indent=2, default=str),
        content_type="application/json",
    )
    response["Content-Disposition"] = f'attachment; filename="workflow_templates_export.json"'
    return response


def workflow_template_import_export_view(request: HttpRequest) -> HttpResponse:
    """
    Combined custom admin view for importing and exporting workflow templates.
    """
    if not request.user.is_staff:
        raise PermissionDenied

    import_form = WorkflowTemplateImportForm()
    export_form = WorkflowTemplateExportForm()

    # Handle POST requests - check which form was submitted
    if request.method == "POST":
        # Check if this is an import submission (has file field)
        if "json_file" in request.FILES:
            import_form = WorkflowTemplateImportForm(request.POST, request.FILES)
            if import_form.is_valid():
                return _handle_template_import(request, import_form)
        else:
            export_form = WorkflowTemplateExportForm(request.POST)
            if export_form.is_valid():
                return _handle_template_export(request, export_form)

    context = {
        "import_form": import_form,
        "export_form": export_form,
        "title": "Workflow Template Import/Export",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/workflow_template_import_export.html", context)
