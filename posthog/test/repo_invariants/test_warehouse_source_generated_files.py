from products.warehouse_sources.backend.facade.credential_auth_types import CREDENTIAL_AUTH_TYPES
from products.warehouse_sources.backend.facade.credential_kinds import CREDENTIAL_KINDS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_auth_type import (
    CREDENTIAL_AUTH_TYPES_PATH,
    frozen_credential_auth_types,
    render_credential_auth_types,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_kind import (
    CREDENTIAL_KINDS_PATH,
    frozen_credential_kinds,
    render_credential_kinds,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    CLASSIFICATION_AUDIT_PATH,
    render_classification_audit,
)


def test_classification_audit_is_up_to_date() -> None:
    assert CLASSIFICATION_AUDIT_PATH.read_text() == render_classification_audit(), (
        "The source field classification audit is out of date. "
        "Run `python manage.py generate_source_field_classification` and commit the result."
    )


def test_credential_auth_types_file_is_up_to_date() -> None:
    assert dict(CREDENTIAL_AUTH_TYPES) == frozen_credential_auth_types()
    assert CREDENTIAL_AUTH_TYPES_PATH.read_text() == render_credential_auth_types(), (
        "The credential auth types are out of date. "
        "Run `python manage.py generate_source_field_classification` and commit the result."
    )


def test_credential_kinds_file_is_up_to_date() -> None:
    assert dict(CREDENTIAL_KINDS) == frozen_credential_kinds()
    assert CREDENTIAL_KINDS_PATH.read_text() == render_credential_kinds(), (
        "The frozen credential kinds are out of date. "
        "Run `python manage.py generate_source_field_classification` and commit the result."
    )
