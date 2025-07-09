from langchain_core.prompts import PromptTemplate


SEMANTIC_FILTER_PROMPT = PromptTemplate.from_template("""
Rate the relevance of each insight to the search query.

Search Query: "{query}"

Insights to rate:
{insights_list}

For each insight, respond with ONLY the number followed by relevance rating:
Format: "1: high, 2: medium, 3: low, 4: none"

Ratings:
- high: Directly matches or strongly relates to the query
- medium: Somewhat related or partially matches
- low: Barely related or generic connection
- none: No meaningful connection

Your response:""")

STRUCTURED_SEMANTIC_FILTER_PROMPT = """
Categorize these insights by relevance to the search query: {query}

Insights:
{insights_list}

Rating criteria:
- high: Exact match or directly relevant
- medium: Partial match or related
- low: Generic connection
- none: No meaningful connection

Note: ⭐ EXACT MATCH insights should generally be 'high' unless unrelated.

Group insight names by relevance level.
"""

IMPROVED_SEMANTIC_FILTER_PROMPT = PromptTemplate.from_template("""
Rate the relevance of each insight to the search query. Pay special attention to exact keyword matches in insight names (marked with ⭐ EXACT MATCH).

Search Query: "{query}"

Insights to rate:
{insights_list}

For each insight, respond with ONLY the number followed by relevance rating:
Format: "1: high, 2: medium, 3: low, 4: none"

Ratings:
- high: Exact keyword match in name OR directly matches query intent
- medium: Partial keyword match OR somewhat related to query
- low: Generic connection to query topics
- none: No meaningful connection

IMPORTANT: Insights marked with ⭐ EXACT MATCH should generally be rated 'high' unless completely unrelated to the query context.

Your response:""")
