# LLM judge input budgets

Online LLM-as-a-judge evaluations apply fixed character budgets to the text sent as the user prompt.
These budgets include transcript headers and line numbers, but exclude the evaluation's system prompt.
They do not change with the selected judge model.

| Target     | Character budget |
| ---------- | ---------------: |
| Generation |          150,000 |
| Trace      |          150,000 |
| Session    |          500,000 |

## Trace and session formatting

Trace and session evaluations first render a text representation with message truncation and line sampling disabled.
This attempt stops when the text exceeds the budget, before assembling the complete oversized transcript in memory.
If the complete rendered transcript fits its budget, the evaluation uses that text.
For sessions, this check includes every trace and the separators between traces, so a large trace can use space left by smaller traces.

If the transcript exceeds its budget, the evaluation formats it again with message truncation enabled.
Each affected content block retains its first 500 and last 500 characters, with a `... (X chars truncated) ...` marker in between.
The formatter then samples lines if the text still exceeds its budget.
Oversized sessions divide their budget evenly across traces, with a minimum allocation of 2,000 characters per trace.
If the assembled fallback session still exceeds 500,000 characters, the evaluation skips it with `session_too_long_to_judge`.

## Generation formatting

Generation evaluations extract message text without the per-message character cutoff.
They sample the combined input, tool definitions, and output only when that text exceeds 150,000 characters, with a final character slice enforcing the limit.

Implementation: [trace judge](../../posthog/temporal/ai_observability/run_trace_evaluation.py), [session judge](../../posthog/temporal/ai_observability/run_session_evaluation.py), and [generation judge](../../posthog/temporal/ai_observability/evaluation_llm_judge.py).
