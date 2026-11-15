from uuid import UUID

from products.account_audits.backend.facade.contracts import AccountAuditRequest, AccountAuditResult, CreatedCredential
from products.account_audits.backend.logic import service


def signing_secret_for(public_key_id: UUID) -> str | None:
    return service.AccountAuditService.signing_secret_for(public_key_id)


def start(payload: AccountAuditRequest, public_key_id: UUID, webhook_id: str) -> AccountAuditResult:
    return service.AccountAuditService.start(payload, public_key_id, webhook_id)


def create_credential(created_by_id: int) -> CreatedCredential:
    return service.AccountAuditService.create_credential(created_by_id)
