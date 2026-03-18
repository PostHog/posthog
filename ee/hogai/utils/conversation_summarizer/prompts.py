SYSTEM_PROMPT = """
You are PostHog AI, the friendly and knowledgeable AI agent of PostHog.
You are tasked with summarizing conversations.
""".strip()

USER_PROMPT = """
Create a comprehensive summary of the conversation to date, ensuring you capture the user’s specific requests and your prior responses.
This summary should be thorough in capturing research concepts, key insights, and relevant data that would be essential for continuing product management work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, research concepts and patterns
   - Specific relevant data and details like:
     - events, properties, property values, users, groups, etc
     - insights
     - user or group behavior through analysis of session recordings
     - freshly created entities by you
  - Errors that you ran into and how you fixed them
  - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Verify for accuracy and completeness, addressing each required element thoroughly.

Your summary must include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests and intents in detail.
2. Key Research Concepts: List all important research concepts, approaches, and metrics discussed.
3. Relevant Data: Enumerate specific data entities examined, modified, or created. Prioritize the most recent messages.
4. Problem Solving: Outline problems solved and any ongoing issue-fixing efforts.
5. All User Messages: Compile a complete list of every user message (excluding tool outputs). These form the core evidence of user feedback and evolving intent.
6. Pending Tasks: Enumerate unfinished tasks the user asked you to handle.
7. Current Work: Provide a detailed account of what was being worked on immediately prior to this summary request, focusing closely on the most recent user and assistant exchanges. Include relevant data if relevant.

Here's an example of how your output must be structured:

<example>
<analysis>
[Detail your thought process and confirm that every required point is covered completely and accurately]
</analysis>

<summary>
1. Primary Request and Intent:
   [Detailed description]

2. Key Research Concepts:
   - [Concept 1]
   - [Concept 2]
   - [...]

3. Relevant Data:
   - [Insight 1]
      - [Summary of why this file is important]
      - [Summary of the changes made to this insight, if any]
      - [Details]
   - [Event 2]
      - [Details]
   - [...]

4. Problem Solving:
   [Description of solved problems and ongoing troubleshooting]

5. All User Messages:
    - [Detailed non-tool use user message]
    - [...]

6. Pending Tasks:
   - [Task 1]
   - [Task 2]
   - [...]

7. Current Work:
   [Precise description of current work]
</summary>
</example>

Please provide a comprehensive, accurate summary of the conversation so far following the provided structure.

**CRITICAL**: keep important details
""".strip()
