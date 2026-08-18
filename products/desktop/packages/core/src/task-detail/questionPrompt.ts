// A question session asks the agent for an answer, not a change. The user's
// prompt leads and this block follows it, so the agent investigates and replies
// instead of editing. The run also starts in plan mode, which enforces it.
export const QUESTION_SESSION_INSTRUCTIONS = `<question_instructions>
Answer the question above. Investigate as much as you need: read the code, query PostHog data, check the docs. Then reply with the answer and the evidence behind it.

Do not edit files, commit, or open a pull request. When the answer implies work, propose the next steps instead of taking them.
</question_instructions>`;
