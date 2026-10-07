from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertConfigurationSourceKind
from products.alerts_platform.backend.presentation.views.platform_alert import SOURCE_KIND_RESOURCE


def test_a_storable_source_kind_is_one_the_contract_names() -> None:
    # `demand.py` builds a `SourceKind` from every due row's stored value, so a kind the column
    # accepts but the contract does not name raises for the whole tick rather than for one row.
    assert {kind.value for kind in PlatformAlertConfigurationSourceKind} <= {kind.value for kind in SourceKind}


def test_every_source_kind_names_the_resource_that_gates_reading_it() -> None:
    # A kind absent from the map never enters `readable`, so its configurations are missing from
    # the read API with nothing raised to say why.
    assert {kind.value for kind in PlatformAlertConfigurationSourceKind} == set(SOURCE_KIND_RESOURCE)
