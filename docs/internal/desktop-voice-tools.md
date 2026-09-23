# Desktop voice tools

The task voice session endpoint accepts `structured_tools: true` for Desktop clients that handle Responses delegation events.
The default remains client delegation for existing builds.
Deploy this backend capability before the corresponding Desktop build.

The server configures `gpt-live-1` for speech and `gpt-5.6-luna` for tool routing, using the existing `OPENAI_LIVE_API_KEY`.
The key needs access to both models.
The same staff, task access, AI consent, feature flag, and request throttling checks apply in either mode.
Cookie sessions use the standard PostHog authentication checks, including required two-factor authentication.
The endpoint creates sessions through the tasks facade.
Session recording remains disabled.

The delegated model can call `send_to_task` and `answer_question`.
Desktop executes these tools through the existing task and question response paths.
It validates the question identity and option IDs before filling the question form, shows voice actions in the UI, and keeps action approvals in the existing approval controls.
Requests to explain an option do not record an answer.
Tool results are returned before the delegated response continues.
The task runs independently of the voice tool response so a clarification answer cannot wait behind the turn it must resume.

Use a local staff account with the voice flag enabled to try multiple questions, option explanations, free-form answers, and action approvals.
Ending voice or leaving the conversation stops microphone capture while the task continues.
