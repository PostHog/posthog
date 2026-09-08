---
name: signals-scout-ai-observability-cache-optimization
description: >
  Finds AI workloads that resend a large prompt prefix without caching it.
  Verifies each gap at the call site in code and reports only fixes with a positive net saving.
scout-tags:
  - ai-observability
---

# AI cache optimization

Watch LLM generation events for workloads that resend a large stable prompt without caching it.
Report a workload only when you have located a code fix that cuts input cost.

- Cached input tokens cost a tenth to half the uncached rate, so caching is one of the cheapest savings available.
- Cache gaps also come back silently: a refactor drops a cache marker, or a new feature injects dynamic content ahead of the stable prompt.
- Hunt both the missing setup and the silent regression.

## Use the packaged analysis skills

Load these preinstalled skills through the runtime's packaged-skill mechanism when relevant:

- `exploring-llm-costs`
- `exploring-llm-traces`
- `querying-posthog-data`

These are packaged runtime skills, not project skill-store entries. Do not use `skill-list` or `skill-get` to load them.

## Avoid duplicate work

- Read this scout's last 14 days of run summaries with `scout-runs-list`. Filter by its exact `skill_name` and current `skill_version`.
- Retrieve details for relevant runs with `scout-runs-retrieve`.
- Search the scratchpad and recent Inbox reports for the workflow, the model, and the call site.
- If a live report covers the same workflow, add only materially new evidence with `scout-edit-report`.
- Never create a second report for an unchanged issue.

## Where to look

- Read `$ai_generation` events from the last 7 days. Window on the ingestion timestamp: prompts change often, so older windows mislead.
- Each row carries `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `input_cost_usd`, `output_cost_usd`, `model`, `provider`, and `input`.
- Exclude corrupt rows before you aggregate: token counts far past the model's context window, and per-call costs far past what the tokens can produce.
- Group rows into workflows. Split on the feature or product tag, the `model`, the `provider`, and the prompt, trace, or span name.
- If the project is multi-tenant, split on the tenant id too.
- A workflow is one product surface plus one model that sends a similar prompt shape many times.

## Token and cost semantics

- Claude models: `input_tokens` excludes cache. Uncached input equals `input_tokens`. Total input adds `cache_read` and `cache_write` on top.
- All other models: `input_tokens` includes cache. Uncached input equals `input_tokens` minus `cache_read`.
- Read the family from the `model` string. The `provider` field is not reliable.
- For cost, add `input_cost_usd` and `output_cost_usd`. Do not trust `total_cost_usd`: it undercounts Claude rows.

## The cache mistakes to hunt

The provider keys a cache entry on the model, the tool definitions, the system content, and the exact token prefix, in request order.
Every mistake below breaks one of those keys.
Name the matching mistake in every report, because the fixes do not overlap.

- **Volatile before stable.** A timestamp, request id, user block, injected memory, or retrieved document sits ahead of the stable prompt. One early changed token invalidates everything after it. Fix: move volatile content to the end, or pin it.
- **No cache marker.** Anthropic caches only where the code sets a `cache_control` breakpoint. Without one, reads stay at zero however stable the prompt. Fix: set the breakpoint at the end of the stable prefix.
- **Marker stripped or dropped.** A wrapper, mixin, or refactor removes an inherited breakpoint. Read the blame before you call it an accident. Fix: restore the marker, unless the recorded reason still holds.
- **Breakpoint too early.** Only the system prompt carries the marker, and the growing conversation history re-bills at the full rate each turn. Fix: cache at the last stable turn, not only the system prompt.
- **Paid writes that nothing reads.** Anthropic bills a cache write at 1.25 times the input rate. A breakpoint on a one-shot path raises the bill. Fix: remove the breakpoint, or raise the reuse.
- **Split caches.** Two call sites send near-identical prompts with different tools, system content, model, or thinking config. They can never share an entry. Fix: align the whole prefix, or accept the split.
- **Calls spaced past the TTL.** Every call writes, and the entry expires before the next call reads it. Fix: raise the reuse rate or extend the cache window.
- **Unstable assembly.** The code serializes the same items in a different order per call. Same content, different prefix, zero hits. Fix: make the assembly deterministic.
- **Repeated identical call.** The same call recurs at a near-constant input size inside one trace. That is usually a retry or compaction loop, not a cache gap. Lead with the loop and mention caching second.

OpenAI, Google, and DeepSeek cache the prefix automatically above a minimum length, so ordering alone fixes them.
Anthropic needs the explicit breakpoint on top of correct ordering.

## Detect an underperforming cache

- Per workflow, compute the cache-hit ratio: `cache_read` divided by the sum of uncached input, `cache_read`, and `cache_write`.
- Compute the uncached input cost: uncached tokens times the input rate. Read the rate from rows with zero cache activity.
- Flag a workflow when its hit ratio sits below its peers and its uncached cost is large.

Compare each flagged workflow against four baselines:

1. Its own past weeks.
2. Other workflows on the same model.
3. The same workflow on its other models.
4. The best-caching workflow in the project.

Baseline 3 catches the classic false positive.
A span name that caches well on its main model and badly on one slice is not an uncached workflow.
The gap lives in that slice, and its fix lives at a different call site.
Name the model slice you mean.

## Verify the data before you touch code

Do:

- Sample the `input` field per workflow.
- Measure the repeat share: how many calls start with the same content.
- Measure the common prefix length in tokens: how far the calls stay identical.
- Check the measured prefix against the provider minimum. Anthropic needs 1024 tokens on Sonnet and Opus and 2048 on Haiku. OpenAI needs 1024. Look up other families.
- Classify the reuse shape. An append-only loop, with many growing calls per trace, pays the most. One call per trace leaves only the cross-trace system prompt. Calls spaced past the TTL pay for writes only.

Do not:

- Do not infer the prefix from a fixed-size hash. A hash of the first 1,500 characters proves about 375 tokens match and says nothing about the rest.
- Do not expect an error below the provider minimum. The provider ignores the breakpoint silently: `cache_creation_input_tokens` stays 0.
- Do not report a workflow whose captured `input` arrives redacted or truncated. You cannot measure the prefix. Hold it.
- Do not expect a breakpoint to fix a one-shot workflow. There is no second call to read the cache back.

## Confirm the fix in code

The data shows that a workflow does not cache.
It cannot show whether that is an oversight, a choice, or unfixable.
This gate removes most false positives: a candidate is not a finding until you have read the code behind it.

Where to look:

- Clone the linked repository once a candidate clears the data checks, not before. Use `gh` read access for anything outside the clone.
- Grep for the span or prompt name, the feature tag, and the model id. The span name usually names the class or chain that builds the request.
- When it resolves to a class, read the base classes too. The volatile injection often lives in a wrapper or mixin, not in the file that names the span.

Answer four questions:

1. Does this call site already cache? A shared helper that caches for another model or caller means the gap lives in one slice. Find that slice's own call site.
2. Is the absence deliberate? Code that strips cache markers records a decision. Read the blame and the pull request behind it. State the reason you found, or state that you looked and found none.
3. Does anything volatile sit in the prefix? If yes, moving or pinning it is the fix, and it comes before any breakpoint.
4. Would the fix cut the bill? Code that summarizes, compacts, reranks, or classifies in one pass has no second call to read the cache back.

Then:

- Name the exact file and function you would change.
- Derive the suggested reviewer from that file, with `CODEOWNERS` or `owners.yaml` when present. The fix belongs to whoever owns the calling code, not to whoever owns the observability data.
- If you cannot find the call site, say so and lower your confidence. Do not present a guess as a located fix.
- Do not fall back to the product's main prompt builder as the target. That path usually caches correctly already.
- If the project has no linked repository, report the finding as unverified. Say which causes you could not rule out, and keep the estimate conservative.

## Estimate the net saving

- Cacheable tokens equal the measured prefix length times the calls that read it back. The first call in each cache window writes and does not read.
- The gross saving equals cacheable tokens times the input rate times the discount: 0.9 for Claude, 0.5 for the auto-cache families.
- Subtract the write cost for providers that charge for writes. A path that mostly writes and rarely reads gets more expensive, not cheaper.
- Report the net figure.
- Never scale a saving by the total tokens of the calls that share a prefix. Only the shared part is cacheable. That mistake turns a short system prompt into a large fake number.

## Do not report

- A workflow where most sampled calls do not share a prefix. The input is unique by construction.
- A workflow whose uncached cost sits below a floor worth a person's attention. Set the floor from the project's overall spend.
- A measured prefix below the provider minimum.
- A one-shot workflow whose cross-trace prefix sits below that minimum.
- An auto-cache model whose prefix already matches.
- A workflow that caches well on another model, when the path you would change is the one that already works.
- A deliberate removal whose recorded reason still holds.
- A negative or trivial net saving.

## When to stop

A finding needs all five. Hold anything that misses one.

1. A repeated prefix above the provider minimum.
2. A hit ratio below peers.
3. Reuse available in the call shape.
4. A fix located in code.
5. A positive net saving.

Title a new report `AI cache optimization: <workflow and cause>`. Include:

- the comparison window
- the measured prefix length
- the reuse shape
- the named mistake from the list above
- the file and function to change
- the net saving

Write memory for held candidates.
Close the run with a short summary: what you checked, what you reported or updated, and what you ruled out.
