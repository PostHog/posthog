---
name: signals-scout-ai-observability-cache-optimization
description: >
  Finds AI workloads that resend a large stable prompt prefix without caching it, verifies the gap
  at the call site in code, and reports only fixes with a positive net saving.
scout-tags:
  - ai-observability
---

# AI cache optimization

Watch LLM generation events for workloads that repeat a large prompt but do not cache it. Report the workloads where a cache fix cuts input cost, and only when you have located the fix in code.

Cached input tokens usually cost a tenth to half the uncached rate, so caching is one of the cheapest savings available. The gaps are also easy to reintroduce without noticing: a refactor drops a cache marker, or a new feature injects dynamic content ahead of the stable prompt. Watch for both the missing setup and the silent regression.

## Use the packaged analysis skills

Load these preinstalled skills through the runtime's packaged-skill mechanism when relevant:

- `exploring-llm-costs`
- `exploring-llm-traces`
- `querying-posthog-data`

These are packaged runtime skills, not project skill-store entries. Do not use `skill-list` or `skill-get` to load them.

## Avoid duplicate work

Read this Scout's last 14 days of run summaries with `scout-runs-list`, filtered by its exact `skill_name` and current `skill_version`. Retrieve relevant details with `scout-runs-retrieve`.

Search the scratchpad and recent Inbox reports for the workflow, model, and call site. If a live report already covers the same workflow, add only materially new evidence with `scout-edit-report`. Skip unchanged issues. Never create a second report for an unchanged issue.

## Data source

Read `$ai_generation` events from the last 7 days, windowed on the ingestion timestamp. Prompts change often, so older windows mislead. Each row carries `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `input_cost_usd`, `output_cost_usd`, `model`, `provider`, and `input`.

Exclude corrupt rows before you aggregate. Token counts far beyond the model's context window, and per-call costs far beyond what the token counts can produce, inflate every total.

## Split into workflows

Group so each row is one repeated workflow, not one mixed bucket. Split on the feature or product tag, the `model`, the `provider`, and the prompt, trace, or span name. In a multi-tenant project, split on the tenant id too.

A workflow is one product surface plus one model that sends a similar prompt shape many times.

## Token semantics

The model family sets how the provider counts input tokens. Handle each family on its own.

- Claude models: `input_tokens` excludes cache. Total input equals `input_tokens` plus `cache_read` plus `cache_write`. Uncached input equals `input_tokens`.
- All other models: `input_tokens` includes cache. Uncached input equals `input_tokens` minus `cache_read`.

Read the family from the `model` string, not the `provider` field. The `provider` field is not reliable.

For cost, add `input_cost_usd` and `output_cost_usd`. Do not trust `total_cost_usd`. It undercounts Claude rows.

## Detect an underperforming cache

For each workflow, compute the cache-hit ratio: `cache_read` divided by the sum of uncached input, `cache_read`, and `cache_write`. Then compute the uncached input cost: uncached input tokens times the workflow input rate. Read the input rate from rows where `cache_read` and `cache_write` are both zero.

Flag a workflow when its hit ratio sits below its peers and its uncached input cost is high. Compare each workflow against four baselines.

1. Its own past weeks.
2. Other workflows on the same model.
3. The same workflow on its other models.
4. The best-caching workflow in the same project.

Baseline 3 catches the classic false positive. A span or prompt name usually covers several models. When the same name caches well on its main model and badly on a smaller slice, the workflow is not uncached: the gap lives in one slice, and its fix lives at a different call site from the one that already caches. Say which model slice you mean.

## Confirm the prefix repeats

A low hit ratio alone proves nothing. Some prompts differ on every call. Before going further, sample the `input` field and measure two separate things per workflow.

- The repeat share: how many calls start with the same content at all.
- The common prefix length: how far into the prompt those calls stay identical, in tokens.

Measure the prefix. Do not infer it from a fixed-size hash: a hash of the first 1,500 characters proves that about 375 tokens match and says nothing about the rest.

Then check the measured prefix against the provider's minimum cacheable prefix. Below the minimum the provider ignores the breakpoint silently: `cache_creation_input_tokens` stays 0 and no error is raised, so no fix is possible there. Anthropic needs 1024 tokens for Sonnet and Opus and 2048 for Haiku. OpenAI needs 1024. For other families, look up the documented minimum rather than assuming there is none.

If the captured `input` is redacted or truncated, you cannot measure the prefix. Hold the candidate rather than reporting an unverifiable one.

## Check the reuse shape

A stable prefix only pays off when a later call reads it back, inside the provider's cache time-to-live. Count the calls per trace or conversation, check whether the prompt grows across them, and check the spacing between calls against the TTL.

- Many calls per trace with a growing prompt: an append-only loop where each turn resends the previous turns. Reuse is real and the saving is large.
- One call per trace: nothing to reuse inside the trace. Only the prefix shared across traces is cacheable, which is usually just the system prompt. Check it against the minimum above.
- Calls spaced past the TTL: every call writes and nothing reads. The fix is the reuse rate or the window, not a breakpoint.

Report the shape you found. A workflow that is one-shot by construction cannot be fixed by a breakpoint, however much it spends.

## What breaks a cache

The provider keys the cache on the model, the tool definitions, the system content, and the exact token prefix, in request order. A single early volatile token invalidates everything after it, and a mismatch in tools or model means two call sites can never share a cache however similar their prompts look.

A cache holds stable content: the system prompt, tool schemas, few-shot examples, fixed documents, and the conversation history up to the last turn. It cannot hold volatile content: the newest user message, per-call retrieved documents, timestamps, request ids, and user ids.

So the fix is usually ordering. Put stable content first, volatile content last, and take timestamps and ids out of the prefix. Anthropic caches only where the code sets a `cache_control` breakpoint: put it at the end of the stable prefix, and cache the growing history at the last stable turn, not only the system prompt. OpenAI, Google, and DeepSeek cache the prefix automatically above a minimum, so ordering alone fixes them.

## Confirm the fix in code

The data shows a workflow does not cache. It cannot show whether that is an oversight, a deliberate choice, or unfixable. Read the call site before reporting. This gate removes most false positives: a candidate that clears the data checks is not a finding until you have read the code behind it.

You can do this. Clone the repository the project is linked to, and use `gh` read access for anything outside the clone. Do the data work first and clone only once a candidate has cleared the checks above.

Find the call site. Grep for the span or prompt name, the feature tag, and the model id. The span name is usually the class, function, or chain that builds the request, so it is the strongest search term. When it resolves to a class, read the class and its base classes: the volatile injection often lives in a wrapper or mixin, not in the file that names the span.

Then answer four questions.

1. Does this call site already cache? If the same class or helper sets a breakpoint for another model or caller, the gap is in one slice. Find that slice's own call site. Do not report against the shared prompt builder that already works.
2. Is the absence deliberate? Code that strips or suppresses cache markers is a design decision until proven otherwise. Read the blame and the pull request that introduced it, and check its review discussion. State in the report either the reason you found or that you looked and found none. A report that reads as "nobody thought of caching here" when someone did gets dismissed.
3. Does anything volatile sit in the prefix? A current timestamp, a request id, or an injected per-call context block ahead of the stable content defeats any breakpoint. If one is there, moving or pinning it is the fix, and it comes before the breakpoint.
4. Would the fix reduce the bill? Re-check the reuse shape against what the code does. Code that summarizes, compacts, reranks, or classifies in a single pass has no second call to read the cache back.

Name the exact file and function you would change, and derive the suggested reviewer from that file, using the repository's ownership files (`CODEOWNERS` or `owners.yaml`) when present. You found the gap in observability data, but the fix belongs to whoever owns the calling code: route the report to them. If you cannot find the call site, say so and lower your confidence. Do not present a guess at the call site as a located fix, and do not fall back to the product's main prompt builder as the target: that is usually the path that already caches correctly.

If the project has no linked repository, report the finding as unverified, say which causes you could not rule out, and keep the estimate conservative.

## Patterns to report

Zero cache reads looks the same in the data whatever the cause. Name the cause in the report, because the fixes do not overlap.

- No breakpoint: the code never marks a prefix, the input repeats, and the prefix clears the minimum. Set a breakpoint at the end of the stable prefix.
- Volatile prefix: a per-call timestamp, id, or injected context block sits ahead of the stable content. Pin or move it first. A breakpoint alone changes nothing.
- Under-caching: the hit ratio sits below peers and the input repeats. Extend the breakpoint to the full stable prefix.
- Cache thrash: `cache_write` runs above `cache_read`. Fix the window or the reuse rate.
- Repeated identical call: the same call recurs at a near-constant input size within one trace or conversation. That is usually a retry or compaction loop, not a caching gap. Lead with "this runs more often than it should" and mention caching only as a secondary mitigation.

And the shapes that are not findings: no reuse available (one call per trace, or the shared prefix sits below the provider minimum), a deliberate removal whose stated reason still holds, a well-cached workflow at peer hit ratio, and low repetition with a repeat share below 0.25.

## Estimate the net saving

Build the estimate from the prefix you measured, not from a constant.

Cacheable tokens equal the measured common prefix length times the number of calls that can read it back. A call reads back only when an earlier call in the same cache window already wrote the prefix, so the first call in each trace writes and does not read.

The gross saving equals cacheable tokens times the input rate times the family discount: 0.9 for Claude, 0.5 for the auto-cache families. For providers that charge for writes, subtract the write cost: Anthropic bills cache writes at 1.25 times the input rate, so a breakpoint on a path that mostly writes and rarely reads raises the bill. Report the net figure. If the net saving is negative or trivial, do not file the finding.

Never scale a saving by the total tokens of the calls that share a prefix. Only the shared part is cacheable. That mistake turns a short system prompt into a large fake number.

## Disqualifiers

Skip a workflow when any of these hold.

- The repeat share sits below 0.25.
- The uncached input cost sits below a floor worth a person's attention. Set the floor from the project's overall spend.
- The measured common prefix sits below the provider's minimum cacheable prefix.
- The workflow is one call per trace and the cross-trace prefix is below that minimum.
- The model caches automatically and the prefix already matches.
- The same workflow already caches well on another model and the path you would change is the one that already works.
- The call site removes caching deliberately and the stated reason still holds.
- The captured `input` is redacted or truncated, so the prefix cannot be measured.

## When to stop

Report only workflows with a repeated prefix above the provider minimum, a low hit ratio, reuse available in the call shape, a fix you located in code, and a positive net saving. Hold the rest.

Title a new report `AI cache optimization: <workflow and cause>`. Include the comparison window, the measured prefix length, the reuse shape, the named cause, the file and function to change, and the net saving. Write memory for held candidates and close the run when nothing clears the bar.

Finish with a short run summary covering what you checked, what you reported or updated, and what you ruled out.
