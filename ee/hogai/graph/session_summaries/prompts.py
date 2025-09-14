GENERATE_FILTER_QUERY_PROMPT = """
<context>
- You get an input - a query the user provided when asking to summarize session recordings
    * "summarize" synonyms: "watch", "analyze", "review", and similar
    * "session recordings" synonyms: "sessions", "recordings", "replays", "user sessions", and similar
- You need to clean it up to keep only the parts to search for session recordings in the database
    * what to keep:
      - dates, times, durations, and similar, to ensure to search in a proper time range
      - devices, locations, OS, and similar, to ensure to apply proper filters
      - user IDs, session IDs, and similar, to ensure to targer specific entities
      - "session recordings" and synonyms to clarify what we search for
    * what to remove:
      - verbs like "summarize" and synonyms, as search focused on finding relevant sessions only
      - summarization-specific instructions (what to prioritize in summaries) as it could obstruct the search
</context>

<input_query>
{input_query}
</input_query>

<examples>
example_1:
- input: "summarize all session recordings from yesterday to find what UX issues users are facing"
- output: "all session recordings from yesterday"

example_2:
- input: "analyze mobile user session recordings from last week, even if 1 second"
- output: "mobile user session recordings from last week, even if 1 second"

example_3:
- input: "hey Max, watch last 300 session recordings of MacOS users from US, I'm curious how are they interacting with the app"
- output: "last 300 session recordings of MacOS users from US"
</examples>

<output_format>
- Return the cleaned up query as a string.
- IMPORTANT: Don't include any other text, formatting, explanation, or comments.
</output_format>
"""
