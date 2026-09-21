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

If the transcript exceeds its budget, the evaluation retries with input history and span content truncated, while keeping generation outputs complete.
Each truncated content block retains its first 500 and last 500 characters, with a `... (X chars truncated) ...` marker in between.
This attempt also stops at the budget and does not sample lines, so a long input does not unnecessarily damage the answer being graded.
Sessions share the full budget across traces during this attempt.

If the transcript still exceeds its budget, the evaluation also truncates generation outputs and samples lines as needed.
This final fallback can omit parts of an answer. It is used only when complete outputs and shortened inputs cannot fit.
In this fallback, sessions divide their budget evenly across traces, with a minimum allocation of 2,000 characters per trace.
If the assembled fallback session still exceeds 500,000 characters, the evaluation skips it with `session_too_long_to_judge`.

## Generation formatting

Generation evaluations extract message text without the per-message character cutoff.
They sample the combined input, tool definitions, and output only when that text exceeds 150,000 characters, with a final character slice enforcing the limit.

Implementation: [trace judge](../../posthog/temporal/ai_observability/run_trace_evaluation.py), [session judge](../../posthog/temporal/ai_observability/run_session_evaluation.py), and [generation judge](../../posthog/temporal/ai_observability/evaluation_llm_judge.py).

## Jev boolean judge

Jev is available under the existing LLM judge option with a customer-provided TypeSafe API key.
Select the key and `jev-1.13.0` on each evaluation; TypeSafe keys cannot become the shared active provider key used by other AI features.
Provider keys keep the provider they were created with; switching providers requires a new key.
Jev supports boolean evaluations only and uses the same formatted text for generation, trace, and session targets.

The evaluation prompt becomes a [Noul question](https://docs.typesafe.ai/primitives/noul).
A probability of at least 0.5 produces `true`; the evaluation's existing pass/fail polarity still applies.
For evaluations that allow N/A, a separate question checks whether the criteria apply, using the same threshold.
Uncertainty alone does not produce N/A.
The raw probability is stored in `$ai_evaluation_probability`, with token usage and the resolved model version.
Jev provides no written reasoning, so reports inspect the original source when explaining outcomes.

TypeSafe rate limits and overload responses are retried through Temporal, honoring `Retry-After` up to five minutes.
If retries fail, the run fails and the evaluation stays enabled.
Invalid probabilities or missing answers fail the evaluation rather than producing a false result.
Inputs rejected for exceeding the model's context window are skipped.
See TypeSafe's [API reference](https://docs.typesafe.ai/api) and [model limits and pricing](https://docs.typesafe.ai/models).
