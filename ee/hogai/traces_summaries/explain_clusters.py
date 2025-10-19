import os
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import structlog
from google import genai
from google.genai.types import GenerateContentConfig

logger = structlog.get_logger(__name__)

CLUSTER_NAME_PROMPT = """
- Analyze this list of chat conversation summaries groups, explaining users' issues
- Summaries were combined into this groups by similarity, so they share a specific topic
- Generate a name for this group that would describe what topic summaries of this group share
- The group name should be concise, up to 10 words
- IMPORTANT: focus on a specific issue, product, or feature the user had problems with
- Start every meaningful word in the title with a capital letter
- Return the name of the group as plain text, without any comments or explanations

```
{summaries}
```
"""


@dataclass(frozen=True)
class ClusterizedSuggestion:
    summary: str
    trace_id: str


@dataclass(frozen=True)
class ClusterizedSuggestionsGroup:
    suggestions: list[ClusterizedSuggestion]
    avg_distance: float
    cluster_label: str


@dataclass(frozen=True)
class ExplainedClusterizedSuggestionsGroup(ClusterizedSuggestionsGroup):
    name: str


class ClusterExplainer:
    def __init__(self, model_id: str, groups_raw: dict[str, Any], summaries_to_trace_ids_mapping: dict[str, str]):
        self._groups_raw = groups_raw
        self._summaries_to_trace_ids_mapping = summaries_to_trace_ids_mapping
        self.model_id = model_id
        self.client = self._prepare_client()

    def explain_clusters(self) -> dict[str, ExplainedClusterizedSuggestionsGroup]:
        enriched_clusters: dict[str, ClusterizedSuggestionsGroup] = {}
        # limit = 5
        # processed_count = 0
        for cluster_label, cluster_raw in self._groups_raw.items():
            enriched_clusters[cluster_label] = self._enrich_cluster_with_trace_ids(
                cluster_raw=cluster_raw, cluster_label=cluster_label
            )
            # processed_count += 1
            # if processed_count >= limit:
            #     break
        named_clusters = self._name_clusters(enriched_clusters)
        # Sort clusters to show the best ones first
        sorted_named_clusters = self.sort_named_clusters(named_clusters)
        return sorted_named_clusters

    @staticmethod
    def _prepare_client() -> genai.Client:
        api_key = os.getenv("GEMINI_API_KEY")
        return genai.Client(api_key=api_key)

    def _name_clusters(
        self, enriched_clusters: dict[str, ClusterizedSuggestionsGroup]
    ) -> dict[str, ExplainedClusterizedSuggestionsGroup]:
        named_clusters: dict[str, ExplainedClusterizedSuggestionsGroup] = {}
        tasks = {}
        for label, cluster in enriched_clusters.items():
            tasks[label] = self._generate_cluster_name(
                # Provide first 5 summaries, should be enough to get the context for the name generation
                summaries=[x.summary for x in cluster.suggestions][:5]
            )
        for label, result in tasks.items():
            current_cluster = enriched_clusters[label]
            named_clusters[label] = ExplainedClusterizedSuggestionsGroup(
                suggestions=current_cluster.suggestions,
                avg_distance=current_cluster.avg_distance,
                cluster_label=current_cluster.cluster_label,
                name=result,
            )
        return named_clusters

    def _generate_cluster_name(self, summaries: list[str]) -> str:
        message = CLUSTER_NAME_PROMPT.format(summaries=json.dumps(summaries))
        config_kwargs = {"temperature": 0}  # Not using any system prompt for saving tokens, as should be good enough
        response = self.client.models.generate_content(
            model=self.model_id, contents=message, config=GenerateContentConfig(**config_kwargs)
        )
        response_text = response.text
        sentences = response.text.split(".")
        if len(sentences) > 1:
            # If LLM generated the explanation (should not) - use the last sentence
            return sentences[-1]
        return response_text

    def _enrich_cluster_with_trace_ids(
        self, cluster_raw: dict[str, Any], cluster_label: str
    ) -> ClusterizedSuggestionsGroup:
        try:
            avg_distance: float = cluster_raw["avg_distance"]
            suggestions: list[str] = cluster_raw["suggestions"]
            suggestions_with_trace_ids: list[ClusterizedSuggestion] = []
            for suggestion in suggestions:
                trace_id = self._summaries_to_trace_ids_mapping[suggestion]
                suggestions_with_trace_ids.append(ClusterizedSuggestion(summary=suggestion, trace_id=trace_id))
            return ClusterizedSuggestionsGroup(
                suggestions=suggestions_with_trace_ids, avg_distance=avg_distance, cluster_label=cluster_label
            )
        except Exception as err:
            raise ValueError(f"Error enriching cluster {cluster_label} with trace IDs: {err}") from err

    @staticmethod
    def sort_named_clusters(
        named_clusters: dict[str, ExplainedClusterizedSuggestionsGroup],
    ) -> dict[str, ExplainedClusterizedSuggestionsGroup]:
        # Sort named clusters by the average distance
        return dict(
            sorted(  # type: ignore
                named_clusters.items(),
                key=lambda item: item[1].avg_distance,  # type: ignore
                reverse=True,
            )
        )


if __name__ == "__main__":
    input_groups_dir_path = Path("/Users/woutut/Documents/Code/posthog/playground/traces-summarization/groups")
    with open(input_groups_dir_path / "groups_25_all.json") as f:
        input_groups_raw: dict[str, Any] = json.load(f)
    with open(input_groups_dir_path / "summaries_to_trace_ids_mapping_25.json") as f:
        input_summaries_to_trace_ids_mapping: dict[str, str] = json.load(f)
    cluster_explainer = ClusterExplainer(
        # Using Flash Lite model as an experiment, but it seems to work pretty good
        model_id="gemini-2.5-flash-lite-preview-09-2025",
        groups_raw=input_groups_raw,
        summaries_to_trace_ids_mapping=input_summaries_to_trace_ids_mapping,
    )
    output_clusters = cluster_explainer.explain_clusters()
    output_clusters_path = input_groups_dir_path / "explained_clusters_25.json"
    with open(output_clusters_path, "w") as f:
        json.dump({key: asdict(value) for key, value in output_clusters.items()}, f)
    logger.info(f"Explained {len(output_clusters)} clusters")
