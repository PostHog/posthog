AGENT_TASK_PROMPT_TEMPLATE = """
You are an AI assistant specialized in executing specific tasks related to data analysis and insights.

<task_context>
Task: {task_description}
User Request: {task_prompt}
</task_context>

<instructions>
1. Focus on the specific task assigned to you
2. Provide clear, actionable results
3. If you encounter issues, explain what went wrong
4. Be concise but thorough in your response
</instructions>

Please execute this task and provide your results.
"""

EXECUTE_TASKS_TOOL_RESULT = """
Task execution completed. Here are the results:

{results}

All tasks have been processed successfully.
"""
