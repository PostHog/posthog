EXTRACT_TOPICS_FROM_QUERY_PROMPT = """
<context>
- You get an input - a query the user provided when asking to summarize LLM traces.
    * "summarize" synonyms: "search", "find", "watch", "analyze", "review", and similar
    * "LLM traces" synonyms: "traces", "trace", "traces analysis", and similar
- You need to clean it up to keep only the parts to search for LLM traces in the database
    * what to keep:
      - topics and keywords to find relevant traces by calculating cosine similarity between the query and the trace summaries
    * what to remove:
      - verbs like "summarize", "fund", and synonyms, as the search should be focused on finding relevant traces only
      - "LLM traces" and synonyms, as it's already clear what we search for
      - dates, times, durations, and similar, as the tool doesn't support filtering by time range yet
      - devices, locations, OS, and similar, as the tool doesn't support filtering by device, location, or OS yet
      - user IDs, session IDs, and similar, as the tool doesn't support filtering by user or session yet
      - summarization-specific instructions (what to prioritize in summaries) as it could obstruct the search
</context>

<input_query>
{input_query}
</input_query>

<examples>
example_1:
- input: "find LLM traces with Google Tag Manager issues"
- output: "Google Tag Manager issues"

example_2:
- input: "search LLM traces to find cases with MP4 export or GIF issues, as I'm concenred about our UX experience"
- output: "MP4 export or GIF issues"

example_3:
- input: "hey Max, check last 300 LLM traces, I'm curious about issues with payment systems, like Stripe, coming from MacOS users from US"
- output: "issues with payment systems, like Stripe"
</examples>

<output_format>
- Return the cleaned up query as a string.
- IMPORTANT: Don't include any other text, formatting, explanation, or comments.
</output_format>
"""
