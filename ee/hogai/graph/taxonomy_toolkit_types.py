from enum import StrEnum


class TaxonomyNodeName(StrEnum):
    """Generic node names for taxonomy agents."""

    LOOP_NODE = "taxonomy_loop_node"
    TOOLS_NODE = "taxonomy_tools_node"
    START = "START"
    END = "END"
