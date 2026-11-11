import json
from typing import cast

from django import forms
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from posthog.admin.console.panels import Owner, ReasonForm
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Output, Page, Row, Secret, Table, ToolOperation
from posthog.models.user import User
from posthog.utils import absolute_uri

from products.account_audits.backend.facade import api as account_audits

GROWTH = Owner(name="Growth", crest="growth")
CREDENTIALS_URL = "/admin/account_audits/accountauditcredential/"
WORKFLOW_BODY = {
    "organization_id": "<organization ID>",
    "reason": "<why this audit is needed>",
    "skill_project": 123,
    "skill_name": "<skill name>",
}


def create_credential(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    created = account_audits.create_credential(cast(User, request.user).pk)
    return Page(
        blocks=(
            Notice(text="In the workflow HTTP action, set these values. The workflow can run in either region."),
            Table(
                columns=("Setting", "Value"),
                rows=(
                    Row(
                        cells=(
                            Cell(text="POST URL"),
                            Cell(text=absolute_uri(reverse("account_audits-start")), mono=True),
                        )
                    ),
                    Row(
                        cells=(
                            Cell(text="X-PostHog-Audit-Key header"),
                            Cell(text=str(created.public_key_id), mono=True),
                        )
                    ),
                ),
            ),
            Secret(label="Signing secret", value=created.signing_secret),
            Notice(
                text=(
                    "Replace the action's default JSON body with the one below. Set skill_project to the numeric ID "
                    "of the project containing the skill in this region. You can also add team_id as a number to "
                    "select the audit target. Other fields, such as event or person, are rejected."
                )
            ),
            Output(text=json.dumps(WORKFLOW_BODY, indent=2)),
            Notice(
                text=(
                    "This credential authorizes audits and skill reads across projects in this region. Keep separate "
                    "credentials for US and EU requests. Publish the workflow changes and verify a request succeeds "
                    "before you disable the old credential."
                ),
                link_text="Manage this credential",
                href=f"{CREDENTIALS_URL}?q={created.public_key_id}",
            ),
        )
    )


@console.register_tool
class AccountAuditCredentialsTool(ConsoleTool):
    key = "account-audit-credentials"
    title = "Account audit credentials"
    owner = GROWTH
    group = "Organizations"
    description = "Creates the signed credential that a workflow uses to start account audits in this region."

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text=(
                        "To rotate, create a credential, configure the workflow with it, and then disable the old "
                        "one in Django admin."
                    ),
                    link_text="Existing credentials",
                    href=CREDENTIALS_URL,
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="create",
                label="Create credential",
                handler=create_credential,
                danger=True,
                form_class=ReasonForm,
                description=(
                    "Creates an active credential that can start account audits and read skills across projects in "
                    "this region. The result page shows the signing secret once."
                ),
                undo_hint=(
                    "Disable the credential in Django admin to revoke it. The signing secret is shown only on the "
                    "next page and cannot be shown again."
                ),
            )
        ]
