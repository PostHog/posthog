from uuid import UUID

import pytest

from products.agent_stack.backend.facade import api
from products.agent_stack.backend.facade.contracts import CreateSplineReticulatorInput
from products.agent_stack.backend.facade.enums import SplineStatus


@pytest.mark.django_db
class TestSplineReticulatorAPI:
    def test_create_and_list(self, team):
        dto = api.create(CreateSplineReticulatorInput(team_id=team.id, name="test-spline"))

        assert isinstance(dto.id, UUID)
        assert dto.name == "test-spline"
        assert dto.status == SplineStatus.PENDING

        all_items = api.list_all()
        assert len(all_items) == 1
        assert all_items[0].id == dto.id
