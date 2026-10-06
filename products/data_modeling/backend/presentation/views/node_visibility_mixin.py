from functools import cached_property
from typing import TYPE_CHECKING

from products.data_modeling.backend.facade.api import NodeVisibility, node_visibility_for

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


class NodeVisibilityMixin:
    user_access_control: "UserAccessControl"
    team_id: int

    @cached_property
    def node_visibility(self) -> NodeVisibility:
        """One answer per request: a viewset instance serves exactly one."""
        return node_visibility_for(self.team_id, self.user_access_control)
