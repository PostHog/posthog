from typing import Generic, TypeVar, TYPE_CHECKING
from posthog.models import Team, User
from ..base import TaxonomyNode

if TYPE_CHECKING:
    from .toolkit import TaxonomyAgentToolkit

State = TypeVar("State")


class TaxonomyAgentNode(Generic[State], TaxonomyNode):
    """Base node for taxonomy agents."""

    toolkit_class: type["TaxonomyAgentToolkit"] | None = None

    def __init__(self, team: Team, user: User, toolkit_class: type["TaxonomyAgentToolkit"] | None = None):
        super().__init__(team, user)
        from .toolkit import TaxonomyAgentToolkit

        toolkit_cls = toolkit_class or self.toolkit_class or TaxonomyAgentToolkit
        self._toolkit = toolkit_cls(team=team)

    def _get_system_prompt(self, state: State) -> str:
        """Get the system prompt for this node. Override in subclasses."""
        raise NotImplementedError


class TaxonomyAgentToolsNode(Generic[State], TaxonomyNode):
    """Base tools node for taxonomy agents."""

    toolkit_class: type["TaxonomyAgentToolkit"] | None = None

    def __init__(self, team: Team, user: User, toolkit_class: type["TaxonomyAgentToolkit"] | None = None):
        super().__init__(team, user)
        from .toolkit import TaxonomyAgentToolkit

        toolkit_cls = toolkit_class or self.toolkit_class or TaxonomyAgentToolkit
        self._toolkit = toolkit_cls(team=team)

    def router(self, state: State) -> str:
        """Route based on the state. Override in subclasses."""
        return "end"
