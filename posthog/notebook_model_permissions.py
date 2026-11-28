from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from products.authorization.backend.facade.api import check
from products.authorization.backend.facade.contracts import CheckRequest, Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.authorization.backend.presentation.resources import resource_for_object

if TYPE_CHECKING:
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
    from products.notebooks.backend.models import Notebook
    from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def can_publish_notebook_model(notebook: Notebook, *, user_id: int) -> bool:
    team_id = notebook.team_id
    subject = Subject(user_id=user_id)
    required = (
        (Resource.project(team_id), Action.VIEW),
        (resource_for_object(notebook), Action.EDIT),
        (Resource(type=ResourceType.QUERY, project_id=team_id), Action.VIEW),
        (Resource(type=ResourceType.WAREHOUSE_TABLE, project_id=team_id), Action.EDIT),
        (Resource(type=ResourceType.WAREHOUSE_VIEW, project_id=team_id), Action.EDIT),
    )
    return all(
        check([CheckRequest(resource=resource, action=action, subject=subject) for resource, action in required])
    )


def can_read_model_upstream_views(views: Iterable[DataWarehouseSavedQuery], *, user_id: int) -> bool:
    subject = Subject(user_id=user_id)
    return all(
        check([CheckRequest(resource=resource_for_object(view), action=Action.VIEW, subject=subject) for view in views])
    )


def can_replace_model_output(table: DataWarehouseTable, *, user_id: int) -> bool:
    return check(resource=resource_for_object(table), action=Action.EDIT, subject=Subject(user_id=user_id))
