from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    CachedTeamTaxonomyQueryResponse,
    TeamTaxonomyItem,
    TeamTaxonomyQuery,
    TeamTaxonomyQueryResponse,
)
from difflib import SequenceMatcher
from typing import Optional, cast
from ee.models.event_definition import EnterpriseEventDefinition
from nltk import ngrams
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from functools import lru_cache
from scipy.sparse import spmatrix

try:
    from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
except ImportError:
    CORE_FILTER_DEFINITIONS_BY_GROUP = {}


class CachedTfidfVectorizer:
    def __init__(self):
        self._vectorizer = TfidfVectorizer()
        self._last_texts = None
        self._last_matrix = None

    def fit_transform(self, texts: list[str]) -> spmatrix:
        if self._last_texts == texts and self._last_matrix is not None:
            return self._last_matrix

        self._last_texts = texts
        self._last_matrix = self._vectorizer.fit_transform(texts)
        return self._last_matrix


# Global instance
_vectorizer = CachedTfidfVectorizer()


def get_event_descriptions_batch(event_names: list[str]) -> dict[str, Optional[str]]:
    """Get event descriptions in batch from either core definitions or enterprise definitions"""
    result: dict[str, Optional[str]] = {}

    # Get from core definitions
    for event_name in event_names:
        if event_core_definition := CORE_FILTER_DEFINITIONS_BY_GROUP.get("events", {}).get(event_name):
            label = event_core_definition.get("label_llm") or event_core_definition.get("label")
            if label:
                description = f"{label}. {event_core_definition.get('description', '')}"
            else:
                description = event_core_definition.get("description", "")
            result[event_name] = description

    # Get remaining from EnterpriseEventDefinition
    remaining_events = {e for e in event_names if e not in result}
    if remaining_events:
        try:
            enterprise_defs = EnterpriseEventDefinition.objects.filter(name__in=remaining_events)
            for def_ in enterprise_defs:
                if def_.description:
                    result[def_.name] = def_.description
        except Exception:
            pass

    # Set None for events without descriptions
    for event_name in event_names:
        if event_name not in result:
            result[event_name] = None

    return result


@lru_cache(maxsize=1000)
def calculate_sequence_similarity(text1: str, text2: str) -> float:
    """Calculate similarity using SequenceMatcher with caching"""
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


@lru_cache(maxsize=1000)
def calculate_ngram_similarity(text1: str, text2: str, n: int = 2) -> float:
    """Calculate similarity using n-grams and Jaccard similarity with caching"""
    text1 = text1.lower()
    text2 = text2.lower()

    # Generate n-grams
    ngrams1 = Counter(ngrams(text1.split(), n))
    ngrams2 = Counter(ngrams(text2.split(), n))

    # Calculate Jaccard similarity
    intersection = sum((ngrams1 & ngrams2).values())
    union = sum((ngrams1 | ngrams2).values())

    return intersection / union if union > 0 else 0.0


def calculate_tfidf_similarity_batch(query: str, texts: list[str]) -> list[float]:
    """Calculate TF-IDF similarity for multiple texts at once"""
    if not texts:
        return []

    all_texts = [query.lower()] + [t.lower() for t in texts]
    tfidf_matrix = _vectorizer.fit_transform(all_texts)

    # Convert sparse matrix to dense array for similarity calculation
    query_matrix = tfidf_matrix[0:1]
    text_matrix = tfidf_matrix[1:]
    similarities = cosine_similarity(query_matrix, text_matrix)

    # Convert to list of floats
    return cast(list[float], similarities[0].tolist())


def calculate_similarity_batch(
    query: str, event_names: list[str], descriptions: dict[str, Optional[str]]
) -> dict[str, float]:
    """Calculate similarity scores for multiple events at once"""
    sequence_similarities = [calculate_sequence_similarity(query, name) for name in event_names]
    ngram_similarities = [calculate_ngram_similarity(query, name) for name in event_names]
    tfidf_similarities = calculate_tfidf_similarity_batch(query, event_names)

    # Adjust similarities based on descriptions
    for i, event_name in enumerate(event_names):
        if desc := descriptions[event_name]:
            desc_sequence = calculate_sequence_similarity(query, desc)
            desc_ngram = calculate_ngram_similarity(query, desc)
            sequence_similarities[i] = max(sequence_similarities[i], desc_sequence)
            ngram_similarities[i] = max(ngram_similarities[i], desc_ngram)

    # Weight and combine similarities
    weights = {"sequence": 0.3, "ngram": 0.4, "tfidf": 0.3}

    return {
        event_name: weights["sequence"] * seq + weights["ngram"] * ngram + weights["tfidf"] * tfidf
        for event_name, seq, ngram, tfidf in zip(
            event_names, sequence_similarities, ngram_similarities, tfidf_similarities
        )
    }


class TeamTaxonomyQueryRunner(TaxonomyCacheMixin, QueryRunner):
    """
    Calculates the top events for a team sorted by count. The EventDefinition model doesn't store the count of events,
    so this query mitigates that.
    """

    query: TeamTaxonomyQuery
    response: TeamTaxonomyQueryResponse
    cached_response: CachedTeamTaxonomyQueryResponse

    def calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="TeamTaxonomyQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # Filter out system/ignored events
        filtered_results = [
            (event, count)
            for event, count in response.results
            if not (event_core_definition := CORE_FILTER_DEFINITIONS_BY_GROUP.get("events", {}).get(event))
            or not (event_core_definition.get("system") or event_core_definition.get("ignored_in_assistant"))
        ]

        # Get all event names for batch processing
        event_names: list[str] = list({event for event, _ in filtered_results})

        # Get descriptions in batch
        descriptions = get_event_descriptions_batch(event_names)

        # Calculate similarities in batch if query plan exists
        similarities = None
        if self.query.plan:
            similarities = calculate_similarity_batch(self.query.plan, event_names, descriptions)

        # Create results
        results: list[TeamTaxonomyItem] = []
        for event, count in filtered_results:
            results.append(
                TeamTaxonomyItem(
                    event=event,
                    count=count,
                    description=descriptions[event],
                    similarity=similarities[event] if similarities is not None else None,
                )
            )

        # Sort by similarity and count
        results.sort(key=lambda x: (-x.similarity if x.similarity is not None else 0, -x.count))

        return TeamTaxonomyQueryResponse(
            results=results, timings=response.timings, hogql=hogql, modifiers=self.modifiers
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        query = parse_select(
            """
                SELECT
                    event,
                    count() as count
                FROM events
                WHERE
                    timestamp >= now () - INTERVAL 30 DAY
                GROUP BY
                    event
                ORDER BY
                    count DESC
                LIMIT 500
            """
        )

        return query
