from typing import get_args

from django.test import SimpleTestCase

from parameterized import parameterized

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import AccountRelationshipSource, OwnershipRoleState


class TestOwnershipVocabulary(SimpleTestCase):
    @parameterized.expand(
        [
            (OwnershipRoleState, contracts.OwnershipRoleStateValue),
            (AccountRelationshipSource, contracts.RelationshipSourceValue),
        ]
    )
    def test_wire_enum_and_contract_literal_agree(self, choices, literal):
        assert set(choices.values) == set(get_args(literal))
