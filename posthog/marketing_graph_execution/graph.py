"""
Graph execution system with dependencies and iteration tracking.
"""

import time
import uuid
import json
import requests
from typing import Any, Optional
from dataclasses import dataclass
from enum import Enum


class NodeStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class GraphNode:
    """Represents a node in the execution graph."""

    node_id: str
    name: str
    dependencies: list[str]
    status: NodeStatus = NodeStatus.PENDING
    result: Optional[dict[str, Any]] = None
    execution_time: float = 0.0
    uuid: str = None

    def __post_init__(self):
        if self.uuid is None:
            self.uuid = str(uuid.uuid4())


class GraphExecutionEngine:
    """Manages graph execution with dependency resolution."""

    def __init__(self):
        self.nodes: dict[str, GraphNode] = {}
        self.execution_context: dict[str, Any] = {}
        self.execution_id = str(uuid.uuid4())

    def add_node(self, node_id: str, name: str, dependencies: list[str] | None = None):
        """Add a node to the graph."""
        if dependencies is None:
            dependencies = []

        self.nodes[node_id] = GraphNode(node_id=node_id, name=name, dependencies=dependencies)

    def validate_dependencies(self) -> bool:
        """Validate that all dependencies exist and no cycles exist."""
        # Check all dependencies exist
        for node in self.nodes.values():
            for dep in node.dependencies:
                if dep not in self.nodes:
                    raise ValueError(f"Node {node.node_id} depends on non-existent node {dep}")

        # Check for cycles using DFS
        visited = set()
        rec_stack = set()

        def has_cycle(node_id: str) -> bool:
            if node_id in rec_stack:
                return True
            if node_id in visited:
                return False

            visited.add(node_id)
            rec_stack.add(node_id)

            for dep in self.nodes[node_id].dependencies:
                if has_cycle(dep):
                    return True

            rec_stack.remove(node_id)
            return False

        for node_id in self.nodes:
            if node_id not in visited:
                if has_cycle(node_id):
                    raise ValueError(f"Cycle detected in graph involving node {node_id}")

        return True

    def get_executable_nodes(self) -> list[str]:
        """Get nodes that can be executed (dependencies satisfied)."""
        executable = []

        for node_id, node in self.nodes.items():
            if node.status != NodeStatus.PENDING:
                continue

            # Check if all dependencies are completed
            deps_satisfied = all(self.nodes[dep].status == NodeStatus.COMPLETED for dep in node.dependencies)

            if deps_satisfied:
                executable.append(node_id)

        return executable

    def execute_node(self, step_id: str, node_id: str) -> dict[str, Any]:
        """Execute a specific node with dummy implementation."""
        node = self.nodes[node_id]
        node.status = NodeStatus.RUNNING

        start_time = time.time()

        # Dummy implementations for each node type
        if step_id == "init":
            result = self._execute_init(node)
        elif step_id == "get_site_content":
            # Get site content and competitor information from API
            result = self._execute_get_site_content(node_id)
        elif step_id == "get_summary":
            result = self._execute_get_summary(node)
        else:
            result = {"status": "completed", "data": f"Executed {step_id}"}

        node.execution_time = time.time() - start_time
        node.result = result
        node.status = NodeStatus.COMPLETED

        # Store result in execution context
        self.execution_context[node_id] = result

        return result

    def _execute_init(self, node: GraphNode) -> dict[str, Any]:
        """Initialize the analysis."""
        time.sleep(0.3)
        website_url = self.execution_context.get("website_url", "unknown")

        return {
            "status": "initialized",
            "target_url": website_url,
            "analysis_id": self.execution_id,
            "timestamp": time.time(),
        }

    def _execute_get_site_content(self, node_id: str) -> dict[str, Any]:
        """Get site content - works for both main site and competitors."""
        time.sleep(1.0 if node_id == "get_site_content" else 0.7)

        # Determine which URL to analyze
        if node_id == "get_site_content":
            # Main site analysis
            website_url = self.execution_context.get("website_url", "unknown")
            is_main_site = True
        else:
            # Competitor analysis - get URL from context
            website_url = self.execution_context.get(f"{node_id}_url", "unknown")
            is_main_site = False

        # Parse domain for analysis
        domain = website_url.split("//")[1].split(".")[0] if "//" in website_url else "unknown"

        # Get competitors using the marketing research API
        competitors = []
        marketing_research_data = None

        try:
            # Call the marketing research API for any site (main or competitor)
            response = requests.post(
                "http://localhost:8000/api/marketing_research/find_competitors/",
                json={
                    "website_url": website_url,
                    "summary_text": f"{domain.title()} is a platform that helps businesses with analytics and insights",
                },
                timeout=100,
            )

            if response.status_code == 200:
                marketing_research_data = response.json()
                # Extract all competitor URLs from the API response
                if marketing_research_data.get("results"):
                    competitors = [result["url"] for result in marketing_research_data["results"]]

        except Exception:
            pass
            # No fallback - just continue with empty competitors

        # Generate site data from API response or use generic data
        if marketing_research_data and "results" in marketing_research_data and marketing_research_data["results"]:
            # Use data from the first result if available (the site itself might be in the results)
            first_result = marketing_research_data["results"][0]
            title = first_result.get("title", f"{domain.title()} - Platform")
            description = first_result.get("summary", f"Platform by {domain.title()}")
            keywords = ["analytics", "platform", domain]
        else:
            # Generic fallback
            title = f"{domain.title()} - Platform"
            description = f"Platform by {domain.title()}"
            keywords = ["analytics", "platform", domain]

        # Generate dynamic SEO score
        seo_score = 70 + (hash(domain) % 30)

        result = {
            "site_data": {
                "url": website_url,
                "title": title,
                "description": description,
                "keywords": keywords,
                "page_load_speed": round(2.0 + (hash(domain) % 10) / 10, 1),
                "seo_score": seo_score,
            },
            "competitors": competitors,
            "metadata": {
                "analysis_depth": "comprehensive" if is_main_site else "competitor",
                "content_pages_analyzed": 15 if is_main_site else 8,
                "social_links_found": 8 if is_main_site else 5,
                "is_main_site": is_main_site,
            },
        }

        # Add marketing research data to the result if available
        if marketing_research_data:
            result["marketing_research_data"] = marketing_research_data

        # TODO: Competitor iterative logic (commented for future use with get their ads)
        # Only create dynamic competitor nodes for the main site
        # if is_main_site:
        #     competitor_node_ids = []
        #     for i in range(len(competitors)):
        #         comp_node_id = f"get_competitor_{i+1}"
        #         comp_url = competitors[i]
        #         if comp_node_id not in self.nodes:
        #             self.add_node(
        #                 node_id=comp_node_id,
        #                 name=f"Analyze competitor: {comp_url}",
        #                 dependencies=["get_site_content"]
        #             )
        #             self.execution_context[f"{comp_node_id}_url"] = comp_url
        #             competitor_node_ids.append(comp_node_id)
        #
        #     # Update get_summary dependencies to include all competitor nodes
        #     if "get_summary" in self.nodes and competitor_node_ids:
        #         current_deps = self.nodes["get_summary"].dependencies
        #         new_deps = list(set(current_deps + competitor_node_ids))
        #         self.nodes["get_summary"].dependencies = new_deps

        return result

    def _execute_get_summary(self, node: GraphNode) -> dict[str, Any]:
        """Generate final summary based on all previous results."""
        time.sleep(0.8)

        # Collect data from all previous nodes
        self.execution_context.get("get_site_content", {})
        competitors = []
        for k, v in self.execution_context.items():
            if k.startswith("get_competitor_") and isinstance(v, dict):
                competitors.append(v)

        total_competitors_found = sum(len(comp.get("competitors", [])) for comp in competitors)

        return {
            "summary": {
                "analyzed_site": self.execution_context.get("website_url"),
                "main_competitors": len(competitors),
                "total_competitor_network": total_competitors_found,
                "market_analysis": {
                    "position": "Strong product analytics leader",
                    "key_differentiators": ["Open source", "All-in-one platform", "Privacy-focused"],
                    "competitive_advantages": ["Feature completeness", "Developer-friendly", "Transparent pricing"],
                },
                "recommendations": [
                    "Expand feature flag capabilities",
                    "Improve onboarding flow",
                    "Strengthen enterprise security features",
                    "Enhance mobile analytics",
                ],
                "execution_stats": {
                    "total_nodes_executed": len([n for n in self.nodes.values() if n.status == NodeStatus.COMPLETED]),
                    "total_execution_time": sum(n.execution_time for n in self.nodes.values()),
                    "analysis_depth": "comprehensive",
                },
            }
        }

    def execute_with_streaming(self, initial_data: dict[str, Any]):
        """Execute the graph with streaming progress updates."""
        # Initialize context
        self.execution_context.update(initial_data)

        # Validate graph
        self.validate_dependencies()

        # Start event
        start_data = {
            "execution_id": self.execution_id,
            "total_steps": len(self.nodes),
            "website_url": initial_data.get("website_url", "unknown"),
            "dependency_graph": {node_id: node.dependencies for node_id, node in self.nodes.items()},
        }
        yield f"event: graph-started\ndata: {json.dumps(start_data)}\n\n"

        # Execute nodes in dependency order
        completed_count = 0
        while completed_count < len(self.nodes):
            executable = self.get_executable_nodes()

            if not executable:
                # Check if we're stuck
                pending_nodes = [n.node_id for n in self.nodes.values() if n.status == NodeStatus.PENDING]
                if pending_nodes:
                    raise RuntimeError(f"Deadlock detected. Pending nodes: {pending_nodes}")
                break

            # Execute all ready nodes (could be parallel in real implementation)
            for node_id in executable:
                node = self.nodes[node_id]

                # Node started event
                node_start_data = {
                    "node_id": node_id,
                    "node_uuid": node.uuid,
                    "name": node.name,
                    "dependencies": node.dependencies,
                    "dependencies_satisfied": True,
                }
                yield f"event: step-started\ndata: {json.dumps(node_start_data)}\n\n"

                # Determine step_id for function mapping
                if node_id == "get_site_content" or node_id.startswith("get_competitor_"):
                    step_id = "get_site_content"
                else:
                    step_id = node_id

                # Execute node
                result = self.execute_node(step_id, node_id)
                completed_count += 1

                # Node completed event
                # Determine step_id, kind, and formatted node_id
                if node_id == "get_site_content":
                    final_step_id = "get_site_content"
                    kind = "get_site_content"
                    formatted_node_id = "get_site_content_0"
                elif node_id == "get_summary":
                    final_step_id = "get_summary"
                    kind = "get_summary"
                    formatted_node_id = "get_summary_0"
                else:
                    final_step_id = node_id
                    kind = "main"
                    formatted_node_id = f"{node_id}_0"

                step_data = {
                    "step_id": final_step_id,  # The actual step type/function
                    "kind": kind,  # get_site_content or get_competitor
                    "node_id": formatted_node_id,  # Formatted with number
                    "step_uuid": node.uuid,
                    "name": node.name,
                    "website_url": initial_data.get("website_url", "unknown"),
                    "execution_time": node.execution_time,
                    "result": result,
                    "dependencies": node.dependencies,
                    "completed_nodes": completed_count,
                    "total_nodes": len(self.nodes),
                }
                yield f"event: step-completed\ndata: {json.dumps(step_data)}\n\n"

        # Final completion event
        final_output = {
            "analysis_complete": True,
            "execution_id": self.execution_id,
            "website_url": initial_data.get("website_url"),
            "nodes_executed": completed_count,
            "total_execution_time": sum(n.execution_time for n in self.nodes.values()),
            "final_results": {
                node_id: {
                    "node_id": node.node_id,
                    "name": node.name,
                    "status": node.status.value,
                    "execution_time": node.execution_time,
                    "result": node.result,
                }
                for node_id, node in self.nodes.items()
            },
        }

        yield f"event: graph-completed\ndata: {json.dumps(final_output)}\n\n"


def create_marketing_analysis_graph() -> GraphExecutionEngine:
    """Create the marketing analysis graph with proper dependencies."""
    graph = GraphExecutionEngine()

    # Define the nodes and their dependencies
    graph.add_node("init", "Initialize Analysis", [])
    graph.add_node("get_site_content", "Analyze Main Site", ["init"])
    # Competitor nodes will be added dynamically when get_site_content completes
    graph.add_node("get_summary", "Generate Summary", ["get_site_content"])

    return graph
