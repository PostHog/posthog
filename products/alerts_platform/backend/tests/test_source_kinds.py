import pytest

from products.alerts_platform.backend.delivery.message import _SOURCE_LABELS
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertConfigurationSourceKind
from products.alerts_platform.backend.presentation.views.platform_alert import (
    SOURCE_KIND_RESOURCE,
    UNSERVED_SOURCE_KINDS,
)


def test_a_storable_source_kind_is_one_the_contract_names() -> None:
    # `demand.py` builds a `SourceKind` from every due row's stored value, so a kind the column
    # accepts but the contract does not name raises for the whole tick rather than for one row.
    assert {kind.value for kind in PlatformAlertConfigurationSourceKind} <= {kind.value for kind in SourceKind}


def test_every_source_kind_names_the_resource_that_gates_reading_it() -> None:
    # A kind absent from the map never enters `readable`, so its configurations are missing from
    # the read API with nothing raised to say why.
    assert {kind.value for kind in PlatformAlertConfigurationSourceKind} == set(
        SOURCE_KIND_RESOURCE
    ) | UNSERVED_SOURCE_KINDS
    assert not set(SOURCE_KIND_RESOURCE) & UNSERVED_SOURCE_KINDS


@pytest.mark.parametrize("source", list(SourceKind))
def test_every_source_kind_names_itself_in_a_message_headline(source: SourceKind) -> None:
    # The headline reads the label by key, so a kind without one raises on every send of its alerts.
    assert _SOURCE_LABELS[source]
