ITERATIVE_SEARCH_SYSTEM_PROMPT = """
Find the 3 most relevant insights matching the user's query from this paginated database.

Search through names, descriptions, and filters for keyword and semantic matches. Use read_insights_page(page_number) to access additional pages if needed.

Return format: [ID1, ID2, ID3] (numbers only, no explanations)

Available insights (Page 1):
{first_page_insights}

{pagination_instructions}
"""

ITERATIVE_SEARCH_USER_PROMPT = """
Search query: {query}

Return format: [ID1, ID2, ID3]
"""

PAGINATION_INSTRUCTIONS_TEMPLATE = """You can read additional pages using the read_insights_page(page_number) tool. Read additional pages until you have found the most relevant insights. There are {total_pages} total pages available (0-indexed). Note: Page 0 data is already provided above in the initial context."""

TOOL_BASED_EVALUATION_SYSTEM_PROMPT = """Evaluate insights for relevance to the user's query: {user_query}

Available Insights:
{insights_summary}

Instructions:
1. {selection_instruction}
2. Use select_insight for the only one relevant match with brief explanation
3. Use reject_all_insights if none match
4. Focus on conceptual relevance (name/description) over technical details
5. Priority: exact matches > specific insights > generic ones
6. Do not be too eager to match an insight to the user's query. If the insight is not relevant or it does not satisfy the properties or filters the user has asked for, reject it.
"""

NO_INSIGHTS_FOUND_MESSAGE = (
    "No existing insights found matching your query. Creating a new insight based on your request."
)

SEARCH_ERROR_INSTRUCTIONS = "INSTRUCTIONS: Tell the user that you encountered an issue while searching for insights and suggest they try again with a different search term."

EMPTY_DATABASE_ERROR_MESSAGE = "No insights found in the database."
