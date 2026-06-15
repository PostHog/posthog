# Skill — choosing the model

Load whenever you're about to set `spec.model` on a new or edited
agent, OR the user asks "which model should I use?" / "is this the
right model?" / "what's the cheapest model that'll work?".

Your job: **recommend a model based on the agent's actual job,
explain the tradeoff clearly, and let the user decide.** Don't
default to the most expensive model out of habit. Don't default to
the cheapest either. Match model to job.

## The cost / quality axes

Three independent dials in roughly increasing cost:

1. **Model family** — Haiku < Sonnet < Opus (Anthropic); GPT-5-mini
   < GPT-5 < GPT-5-thinking (OpenAI); Gemini-flash < Gemini-pro.
   Within a vendor each step up is ~3-8× the per-token cost.
2. **Reasoning level** (`spec.reasoning`) — `minimal` < `low` <
   `medium` < `high` < `xhigh`. Adds deliberation tokens, multiplies
   per-turn cost. Only meaningful for `high`+ on reasoning-heavy
   tasks; for skim-and-respond agents it's pure waste.
3. **Context budget** (`spec.limits.max_output_tokens` + conversation
   length over multi-turn) — longer conversations re-feed the whole
   history each turn, so multi-turn agents pay quadratically.

A small Haiku agent with `reasoning: minimal` on short
conversations runs ~$0.01/session. A Sonnet agent at `reasoning:
high` on 50-turn debugging sessions runs ~$3/session. Two orders of
magnitude, same platform.

## The decision flowchart

Walk this with the user — out loud, not in your head. The skill
they're paying for is your reasoning, not your answer.

```text
What's the job?
├── Short, formulaic, no reasoning ........ Haiku, reasoning: minimal
│     ("look up a thing and reply")          (slack lookup bots, FAQ bots,
│                                             webhook responders)
├── Multi-step but bounded ................ Sonnet, reasoning unset
│     ("query data, format an answer")       (analytics summaries, status
│                                             reports, structured drafts)
├── Open-ended reasoning, single hop ...... Sonnet, reasoning: medium
│     ("triage this alert, suggest a fix")   (oncall triage, code review,
│                                             planning, light debugging)
├── Long, branching, with backtracking .... Sonnet, reasoning: high
│     ("debug this failing session, work     (the concierge itself, deep
│       through hypotheses")                 investigations, multi-turn
│                                             editing flows)
└── Cutting edge / research-grade ......... Opus / GPT-5-thinking, high
      ("solve this novel problem")           (rare — flag the cost
                                              explicitly to the user)
```

Default recommendation when uncertain: **`anthropic/claude-sonnet-4-6`
with `reasoning` unset.** It's the platform's stable workhorse —
good enough for almost anything, not embarrassingly expensive for
the simple cases.

## The conversation to have

When the user says "build me an agent that does X" without naming a
model, do this — IN ORDER, don't skip the asking:

1. **Describe the job back to them in one sentence.** "You want a bot
   that, when @-mentioned in Slack, looks up who's on call and
   replies in-thread. Is that right?"
2. **Place the job on the flowchart.** Out loud. "That's a
   short-formulaic-no-reasoning job — one API call, one reply, no
   branching."
3. **Recommend with the cost tradeoff stated.** "I'd recommend
   `anthropic/claude-haiku-4-5` at `reasoning: minimal`. Expected
   cost: ~$0.005-$0.02 per @-mention. A Sonnet equivalent would be
   ~$0.05-$0.20 per @-mention — 10× more for no quality difference
   on this job."
4. **Offer the user the upgrade explicitly.** "If you'd rather pay
   more for slightly better natural-language framing of the reply,
   I can use Sonnet. Or if you want the cheapest possible, we can
   try `anthropic/claude-haiku-4-5` at `reasoning: minimal` and see
   if the replies feel right. Which way do you want to go?"
5. **Wait for the user's pick.** Don't default. Don't assume. Don't
   "just go with Sonnet to be safe."

For the open-ended reasoning cases the conversation flips: lead with
"this job benefits from deliberation; I'd recommend Sonnet with
`reasoning: medium`, ~$0.20-$0.50 per session. A Haiku version
might cost $0.02/session but you'll see it miss things on harder
inputs. Want me to start with Sonnet and we can dial down if
sessions feel over-budget?"

## When to push back on the user

The user might ask for the wrong model. Push back gently:

- **User picks Opus / GPT-5-thinking for a lookup bot.** "Opus on a
  one-API-call agent is a ~50× cost markup for zero quality win on
  this job. I'd recommend Haiku — happy to upgrade if you see
  quality issues, but starting at Opus is paying for capability you
  can't use here."
- **User picks Haiku for a debugging agent.** "Haiku tends to miss
  the subtle hypotheses on multi-turn debugging — the kind of agent
  that helps less than it costs to run. I'd recommend Sonnet
  starting point. If cost matters, we can put a tight
  `max_wall_seconds` / `max_turns` to cap session cost."
- **User picks `reasoning: xhigh` on anything that isn't research-
  grade.** "`xhigh` adds 5-10× the per-turn cost for diminishing
  returns past `high`. Worth it for truly novel problems; for almost
  every other case `high` matches the quality at a fraction of the
  cost."

## Cost estimation when the user asks

For the rough back-of-envelope:

| Model                         | Input $/1M tok | Output $/1M tok | Notes                                   |
| ----------------------------- | -------------- | --------------- | --------------------------------------- |
| `anthropic/claude-haiku-4-5`  | ~$0.80         | ~$4             | Fast, cheap, good at structured work    |
| `anthropic/claude-sonnet-4-6` | ~$3            | ~$15            | Platform default; balanced quality/cost |
| `anthropic/claude-opus-4-7`   | ~$15           | ~$75            | High-end reasoning; rare to need        |
| `openai/gpt-5-mini`           | ~$0.25         | ~$2             | Cheapest competent option               |
| `openai/gpt-5`                | ~$2.50         | ~$10            | OpenAI workhorse                        |
| `openai/gpt-5-thinking`       | ~$15           | ~$60            | Heavy reasoning, similar tier to Opus   |

(These shift; ground-truth lives in
`@posthog/get-llm-total-costs-for-project` for actual billed rates.
Use this table for ballparking the conversation, not for invoices.)

Quick session-cost arithmetic, for the recommendation conversation:

```text
session cost ≈ (avg_input_tokens × input_rate)
              + (avg_output_tokens × output_rate)
              × turns
              × reasoning_multiplier
```

Reasoning multipliers (rough): unset/minimal = 1×, low = 1.3×,
medium = 1.8×, high = 3×, xhigh = 6×.

You don't need to be exact. You need to give the user "$0.01 or
$1?" precision so they can make a real choice.

## What "good" looks like

A good model-pick conversation finishes with:

- The user said which model they want.
- The user understood why you suggested it.
- The user understood roughly what it'll cost per session.
- The agent's `spec.model` is set.
- If reasoning matters, `spec.reasoning` is set explicitly (not
  defaulted).
- If session cost matters, `spec.limits.max_turns` /
  `max_wall_seconds` reflect the cap the user chose.

Don't write the spec until the user has explicitly picked.
