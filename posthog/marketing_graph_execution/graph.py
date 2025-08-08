"""
Graph execution system with dependencies and iteration tracking.
"""

import time
import uuid
import json
import logging
from typing import Any, Optional
from dataclasses import dataclass
from enum import Enum
from products.marketing_researcher.backend.service import MarketingResearcherService

logger = logging.getLogger(__name__)


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
        self.streaming_callback = None

        try:
            self.marketing_researcher_service = MarketingResearcherService()
        except ImportError:
            logger.warning("Marketing researcher service not available")
            self.marketing_researcher_service = None

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

        # Implementations for each node type
        if step_id == "init":
            result = self._execute_init(node)
        elif step_id == "find_competitors":
            result = self._execute_find_competitors(node_id)
        elif step_id == "enrich_competitors":
            result = self._execute_enrich_competitors(node_id)
        elif step_id == "generate_recommendations":
            result = self._execute_generate_recommendations(node_id)
        elif step_id == "analyze_web_presence":
            result = self._execute_analyze_web_presence(node_id)
        elif step_id == "get_site_content":
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

    def _execute_find_competitors(self, node_id: str) -> dict[str, Any]:
        website_url = self.execution_context.get("website_url", "unknown")
        summary_text = self.execution_context.get("summary_text", f"Platform for analytics and insights")

        try:
            if self.marketing_researcher_service and self.marketing_researcher_service.is_available:
                result = self.marketing_researcher_service.find_competitors_only(website_url, summary_text)
                return {
                    "competitors_found": result["total_competitors"],
                    "competitors": result["competitors"],
                    "query_processed": result["query_processed"],
                    "target_company": result["target_company"],
                    "status": "completed",
                }
            else:
                logger.warning("Marketing researcher service not available")

        except Exception as e:
            logger.exception(f"Error finding competitors: {e}")

        return {"competitors_found": 0, "competitors": [], "status": "failed", "error": "Could not find competitors"}

    def _execute_analyze_web_presence(self, node_id: str) -> dict[str, Any]:
        """Analyze current web presence of the target company using marketing researcher service."""
        website_url = self.execution_context.get("website_url", "unknown")

        try:
            if not self.marketing_researcher_service:
                raise Exception("Marketing researcher service not available")

            # Use the marketing researcher service to analyze web presence
            result = self.marketing_researcher_service.analyze_web_presence(website_url)
            return result

        except Exception as e:
            logger.exception(f"Error analyzing web presence: {e}")
            return {
                "web_presence": {"status": "failed", "error": str(e)},
                "status": "failed",
                "error": str(e),
            }

    def _execute_enrich_competitors(self, node_id: str) -> dict[str, Any]:
        """Enrich competitors progressively, streaming each enriched competitor as it becomes available."""
        # Get competitors from previous node
        find_result = self.execution_context.get("find_competitors", {})
        competitors = find_result.get("competitors", [])

        if not competitors:
            return {"enriched_competitors": [], "status": "failed", "error": "No competitors to enrich"}

        top_competitors = competitors[:5]
        remaining_competitors = competitors[5:]

        logger.info(f"Progressive enrichment: processing {len(top_competitors)} competitors")

        try:
            if not self.marketing_researcher_service or not self.marketing_researcher_service.is_available:
                return {
                    "enriched_competitors": competitors,
                    "enrichment_count": 0,
                    "status": "failed",
                    "error": "Marketing researcher service not available",
                }

            enriched_competitors = []

            # Process each competitor individually and emit streaming events
            for i, competitor in enumerate(top_competitors):
                competitor_url = competitor.get("url")
                if not competitor_url:
                    enriched_competitors.append(competitor)
                    continue

                # Enrich individual competitor
                competitor_start_time = time.time()
                seo_data = self.marketing_researcher_service._extractor.extract_marketing_data(competitor_url)
                competitor_time = time.time() - competitor_start_time

                enriched_competitor = {**competitor, "seo_data": seo_data}
                enriched_competitors.append(enriched_competitor)

                # Stream this enriched competitor immediately if callback is available
                if self.streaming_callback:
                    enriched_data = {
                        "event_type": "competitor_enriched",
                        "competitor": enriched_competitor,
                        "index": i,
                        "total": len(top_competitors),
                        "processing_time": competitor_time,
                    }
                    self.streaming_callback({"event": "competitor-enriched", "data": json.dumps(enriched_data)})

                logger.info(f"Enriched competitor {i+1}/{len(top_competitors)}: {competitor.get('title', 'Unknown')}")

            final_competitors = enriched_competitors + remaining_competitors

            return {
                "enriched_competitors": final_competitors,
                "enrichment_count": len(enriched_competitors),
                "progressive_enrichment": True,
                "status": "completed",
            }

        except Exception as e:
            logger.exception(f"Error in progressive enrichment: {e}")
            return {
                "enriched_competitors": competitors,  # Return original if enrichment fails
                "enrichment_count": 0,
                "status": "failed",
                "error": str(e),
            }

    def _execute_generate_recommendations(self, node_id: str) -> dict[str, Any]:
        """Generate marketing recommendations using marketing researcher service."""

        enrich_result = self.execution_context.get("enrich_competitors", {})
        enriched_competitors = enrich_result.get("enriched_competitors", [])
        find_result = self.execution_context.get("find_competitors", {})
        target_company = find_result.get("target_company", {})

        if not enriched_competitors:
            return {"recommendations": "No competitors available for analysis", "status": "failed"}

        try:
            if not self.marketing_researcher_service or not self.marketing_researcher_service.is_available:
                return {
                    "marketing_recommendations": "Marketing researcher service not available",
                    "status": "failed",
                    "error": "Service not initialized",
                }

            # Use the marketing service to generate recommendations
            result = self.marketing_researcher_service.generate_marketing_recommendations(
                enriched_competitors, target_company
            )

            return result

        except Exception as e:
            logger.exception(f"Error generating recommendations: {e}")

            return {
                "marketing_recommendations": "Could not generate recommendations due to technical error",
                "status": "failed",
                "error": str(e),
            }

    def _execute_init(self, node_id: str) -> dict[str, Any]:
        """Initialize the analysis."""
        website_url = self.execution_context.get("website_url", "unknown")

        return {
            "status": "initialized",
            "target_url": website_url,
            "analysis_id": self.execution_id,
            "timestamp": time.time(),
        }

    def execute_with_streaming(self, initial_data: dict[str, Any]):
        """Execute the graph with streaming progress updates."""
        # Initialize context
        self.execution_context.update(initial_data)

        # Set up streaming callback for real-time events during execution
        streaming_events = []

        def streaming_callback(event_data):
            streaming_events.append(event_data)

        self.streaming_callback = streaming_callback

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
                elif node_id in ["find_competitors", "enrich_competitors", "generate_recommendations"]:
                    step_id = node_id
                else:
                    step_id = node_id

                # Execute node
                result = self.execute_node(step_id, node_id)

                # Yield any streaming events that occurred during execution
                while streaming_events:
                    event = streaming_events.pop(0)
                    yield event

                completed_count += 1

                # Special handling for immediate streaming after node completion
                if node_id == "analyze_web_presence":
                    # Stream web presence analysis results
                    web_presence_data = {
                        "event_type": "web_presence_analyzed",
                        "web_presence": result.get("web_presence", {}),
                        "target_url": result.get("web_presence", {}).get("target_url", ""),
                        "analysis_summary": result.get("web_presence", {}).get("analysis_summary", {}),
                    }
                    yield {"event": "web-presence-analyzed", "data": json.dumps(web_presence_data)}
                elif node_id == "find_competitors":
                    # Immediately stream competitors list after finding them
                    competitors_data = {
                        "event_type": "competitors_found",
                        "competitors": result.get("competitors", []),
                        "total_competitors": result.get("competitors_found", 0),
                        "target_company": result.get("target_company", {}),
                        "query_processed": result.get("query_processed", ""),
                    }
                    yield {"event": "competitors-found", "data": json.dumps(competitors_data)}

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
                elif node_id == "find_competitors":
                    final_step_id = "find_competitors"
                    kind = "find_competitors"
                    formatted_node_id = "find_competitors_0"
                elif node_id == "enrich_competitors":
                    final_step_id = "enrich_competitors"
                    kind = "enrich_competitors"
                    formatted_node_id = "enrich_competitors_0"
                elif node_id == "generate_recommendations":
                    final_step_id = "generate_recommendations"
                    kind = "generate_recommendations"
                    formatted_node_id = "generate_recommendations_0"
                elif node_id == "analyze_web_presence":
                    final_step_id = "analyze_web_presence"
                    kind = "analyze_web_presence"
                    formatted_node_id = "analyze_web_presence_0"
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
    """Create a marketing analysis graph that streams results as they become available."""
    graph = GraphExecutionEngine()

    graph.add_node("init", "Initialize Analysis", [])
    graph.add_node("analyze_web_presence", "Analyze Current Web Presence", ["init"])
    graph.add_node("find_competitors", "Find Competitors", ["analyze_web_presence"])
    graph.add_node("enrich_competitors", "Enrich Competitors", ["find_competitors"])
    graph.add_node("generate_recommendations", "Generate Marketing Recommendations", ["enrich_competitors"])

    return graph
