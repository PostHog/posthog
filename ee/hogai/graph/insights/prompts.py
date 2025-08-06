ITERATIVE_SEARCH_SYSTEM_PROMPT = """
You are an expert at finding relevant insights from a large database. Your task is to find the 3 most relevant insights that match the user's search query.

You have access to a paginated database of insights. The first page has been loaded for you below. You can read additional pages using the read_insights_page tool if needed.

Each insight has:
- ID: Unique numeric identifier
- Name: The insight name
- Description: Optional description of what the insight shows
- Filters: Optional filters used to create the insight
- Query: The query used to create the insight

Guidelines:
1. Focus on finding insights that directly relate to the user's search query
2. Look for keyword matches in names and descriptions
3. Consider semantic similarity and practical usefulness
4. You can iterate through pages to find better matches
5. Stop when you have found 3 highly relevant insights OR you've exhausted reasonable search options
6. Return the 3 insight IDs in your final response

Available insights (Page 1):
{first_page_insights}

{pagination_instructions}
"""

ITERATIVE_SEARCH_USER_PROMPT = """
Find 3 insights matching this search query: {query}

Return the insight IDs as a list of numbers.
"""

PAGINATION_INSTRUCTIONS_TEMPLATE = """You can read additional pages using the read_insights_page(page_number) tool. Read additional pages until you have found the most relevant insights. There are {total_pages} total pages available (0-indexed)."""

HYPERLINK_USAGE_INSTRUCTIONS = "\n\nINSTRUCTIONS: When mentioning insights in your response, always use the hyperlink format provided above. For example, write '[Weekly signups](/project/123/insights/abc123)' instead of just 'Weekly signups'."

TOOL_BASED_EVALUATION_SYSTEM_PROMPT = """You are evaluating existing insights to determine which ones (if any) match the user's query.

User Query: {user_query}

Available Insights:
{insights_summary}

Instructions:
1. {selection_instruction}
2. Use get_insight_details if you need more information about an insight before deciding
3. If you find suitable insights, use select_insight for each one with a clear explanation of why it matches
4. If none of the insights are suitable, use reject_all_insights with a reason
5. Be selective - only choose insights that truly match the user's needs
6. When multiple insights could work, prioritize:
   - Exact matches over partial matches
   - More specific insights over generic ones
   - Insights with clear descriptions over vague ones"""

NO_INSIGHTS_FOUND_MESSAGE = (
    "No existing insights found matching your query. Creating a new insight based on your request."
)

SEARCH_ERROR_INSTRUCTIONS = "INSTRUCTIONS: Tell the user that you encountered an issue while searching for insights and suggest they try again with a different search term."

EMPTY_DATABASE_ERROR_MESSAGE = "No insights found in the database."
