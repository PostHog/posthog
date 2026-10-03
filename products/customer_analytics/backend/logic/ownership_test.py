from typing import get_args

from parameterized import parameterized

from posthog.test.clickhouse_free import ClickhouseFreeSimpleTestCase

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import (
    AccountRelationshipSource,
    OwnershipRoleDiagnostic,
    OwnershipRoleState,
)


class TestOwnershipVocabulary(ClickhouseFreeSimpleTestCase):
    @parameterized.expand(
        [
            (OwnershipRoleState, contracts.OwnershipRoleStateValue),
            (AccountRelationshipSource, contracts.RelationshipSourceValue),
            (OwnershipRoleDiagnostic, contracts.OwnershipRoleDiagnosticValue),
        ]
    )
    def test_wire_enum_and_contract_literal_agree(self, choices, literal):
        assert set(choices.values) == set(get_args(literal))
