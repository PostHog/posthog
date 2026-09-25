---
name: dynamic-workflows
description: >-
  Designs and runs task-specific JavaScript harnesses with the `workflow` tool. Use for broad,
  long-running, highly structured, or adversarial work that benefits from many isolated agents:
  exhaustive audits, root-cause investigations, research, large triage queues, competing proposals,
  repeated verification, and independent changes across disjoint files. Covers decomposition patterns,
  agent and model routing, structured handoffs, failure handling, and the workflow runtime API.
---

# Dynamic workflows

The `workflow` tool runs a JavaScript program that coordinates isolated subagents. Use the program as a task-specific harness: JavaScript owns iteration, routing, barriers, and completion checks, while each `agent()` call handles one focused unit of work in a fresh context window.

Only the script's return value enters the parent context. Intermediate results stay inside the workflow, while structured progress and logs remain visible in the tool call. End broad workflows with a compact synthesis instead of returning every worker transcript.

This separation is useful when one long conversation would make it hard to remain complete, impartial, or faithful to the original goal. It is not a default for ordinary work. More agents mean more latency and token use.

## Decide whether a workflow earns its cost

Use a workflow when at least one of these is true:

- **Breadth:** the task covers many independent files, records, systems, claims, or alternatives.
- **Structure:** the work needs explicit stages, routing, aggregation, or a completion condition.
- **Independent judgment:** a result should be challenged by an agent that did not produce it.
- **Competing approaches:** several agents should attempt the same problem before a separate judge chooses.
- **Unknown work size:** the task should repeat until no unresolved items or new findings remain.
- **Context isolation:** each unit benefits from a clean context that contains only its evidence and rubric.

Good requests include:

- Audit every ingestion stage for one invariant, then verify each reported violation.
- Form independent explanations for a production symptom and try to disprove each one.
- Generate several migration plans, compare their risks, and return one tested recommendation.
- Classify a large issue backlog, deduplicate related reports, and prepare actions for confirmed groups.
- Check every factual statement in a technical report against primary evidence.
- Apply the same independent change across disjoint packages, then review the combined diff.

Do not use a workflow for:

- One question, one investigation, or one edit.
- One or two independent delegations. Use `subagent` parallel mode instead.
- Work where nearly all parent conversation context is essential.
- Several writers that would edit the same files or shared state concurrently.
- A routine task where direct execution is cheaper and easier to verify.

## Define success before writing JavaScript

Write down these decisions first:

1. **Final outcome:** what compact value must the workflow return?
2. **Work units:** what list will the script iterate over?
3. **Evidence:** what must each worker cite or return?
4. **Rubric:** what makes an item pass, fail, rank higher, or require another pass?
5. **Coverage:** how will the result prove that every required item was processed?
6. **Failure policy:** which failures may become `null`, and which must stop the workflow?
7. **Write boundaries:** which agents may edit, and can their files overlap?

Keep these decisions in JavaScript variables, schemas, and stop conditions. Do not rely on one agent to remember the whole plan across a large run.

## Choose an orchestration pattern

Patterns compose. Use the smallest combination that creates a reliable feedback loop.

### Classify and act

Use one agent to assign each item to a small set of categories, then route each category to a specialized prompt or agent.

Use it for mixed backlogs, heterogeneous files, and requests where not every item needs the same treatment. Keep classification structured and include an `unknown` route. Do not force uncertain items into a confident category.

### Fan out and synthesize

Map independent items to agents, wait for all results, then give a bounded set of structured outputs to one synthesis agent.

Use it for broad audits, research, and repeated checks. The synthesis step is a barrier: it runs only after the fan-out settles. Return coverage and failures with the synthesis so missing work stays visible.

### Adversarial verification

Separate production from judgment. A worker proposes a finding or change; another agent checks it against an explicit rubric and evidence.

Use it when false positives, unsupported claims, or self-review bias would be costly. A verifier must receive the original requirement and evidence, not only the worker's conclusion.

### Generate and filter

Ask several agents for candidates, normalize and deduplicate them, then use a separate agent to reject weak candidates against a rubric.

Use it for designs, names, hypotheses, and solution exploration. Preserve reasons for rejection when they help the final decision.

### Tournament

Have multiple agents solve the same task independently. Compare two candidates at a time with a judge until one or a small shortlist remains.

Use comparative judgment when absolute scores would be vague. Randomize or rotate candidate order when ordering could bias the judge. Do not let an author judge its own output.

### Loop until done

Repeat discovery and action until a measurable stop condition is true, such as no failing tests, no unprocessed items, or no new evidence after a pass.

Always set a hard pass or agent limit. Track what changed between passes. Stop if a pass makes no progress, and return the unresolved state instead of claiming completion.

### Independent hypothesis testing

Give separate agents disjoint evidence or different investigative methods. Ask each to state a hypothesis, predicted observations, and a disproof test. Then use another stage to compare surviving explanations.

Use it for root-cause analysis. Testing only the first plausible explanation recreates the bias the workflow is meant to avoid.

### Quarantine and act

Let read-only agents inspect untrusted or noisy inputs. Convert their findings into a narrow structured format. Give write capability only to a later agent that receives the validated structure and trusted instructions.

Use it for public content, support queues, issue bodies, and other prompt-injection surfaces. This reduces exposure but is not a security boundary. Never pass secrets or unnecessary sensitive data to agents.

### Model routing

Use Luna for tightly specified classification and simple checks, Terra for moderate analysis, and Sol for open-ended exploration or difficult judgment.

Base routing on observable complexity, not arbitrary variety. Spend stronger models where they can change the outcome.

## Design for independent contexts

Agents do not share your conversation or each other's transcripts. Each prompt must contain:

- The exact task and completion condition.
- Relevant paths, inputs, and constraints.
- The evidence or artifact names it may use.
- The required output shape.
- What the next stage needs from the result.

Do not ask an agent to "continue the investigation above." Pass the required prior result through a named artifact or inline input.

Use `schema` for machine-consumed outputs. The runtime parses the final JSON and enforces the top-level object or array shape plus required keys. The full schema is also included in the agent prompt. Keep schemas small and validate critical semantics in a later agent or in JavaScript.

## Prefer a declared plan

Use a literal `meta` plan for workflows with known phases and artifact dependencies. It makes the live progress display useful and lets the runtime reject missing, duplicate, or out-of-order artifacts.

```javascript
export const meta = {
  name: 'review_auth_boundaries',
  goal: 'Find and verify authorization gaps across three layers',
  inputs: [],
  phases: [
    {
      title: 'Investigate',
      goal: 'Collect independent evidence',
      inputs: [],
      produces: ['api evidence', 'service evidence', 'ui evidence', 'combined evidence'],
    },
    {
      title: 'Challenge',
      goal: 'Reject unsupported findings',
      inputs: ['combined evidence'],
      produces: ['reviewed findings'],
    },
    {
      title: 'Synthesize',
      goal: 'Return the verified report',
      inputs: ['reviewed findings'],
      produces: ['final report'],
    },
  ],
  synthesis: {
    phase: 'Synthesize',
    inputs: ['reviewed findings'],
    produces: ['final report'],
  },
}

const findingsSchema = {
  type: 'object',
  required: ['area', 'findings', 'filesChecked'],
  properties: {
    area: { type: 'string' },
    findings: { type: 'array' },
    filesChecked: { type: 'array' },
  },
}

phase('Investigate')
const evidence = await parallel([
  () => agent('Audit API authorization boundaries. Cite each checked file.', {
    agent: 'Explore',
    label: 'API boundary audit',
    objective: 'Find API authorization gaps and report complete coverage.',
    inputs: [],
    produces: 'api evidence',
    schema: findingsSchema,
  }),
  () => agent('Audit service-layer authorization boundaries. Cite each checked file.', {
    agent: 'Explore',
    label: 'Service boundary audit',
    objective: 'Find service authorization gaps and report complete coverage.',
    inputs: [],
    produces: 'service evidence',
    schema: findingsSchema,
  }),
  () => agent('Audit UI assumptions that could expose unauthorized actions. Cite each checked file.', {
    agent: 'Explore',
    label: 'UI boundary audit',
    objective: 'Find unsafe UI authorization assumptions and report complete coverage.',
    inputs: [],
    produces: 'ui evidence',
    schema: findingsSchema,
  }),
])

const completedEvidence = evidence.filter(Boolean)
if (completedEvidence.length !== evidence.length) {
  throw new Error('One or more investigation branches failed')
}
publish('combined evidence', completedEvidence)

phase('Challenge')
const reviewed = await agent(
  'Check each supplied finding against code evidence. Reject speculative findings. Return JSON.',
  {
    agent: 'Plan',
    model: 'strong',
    label: 'Authorization skeptic',
    objective: 'Keep only reproducible authorization gaps and identify missing coverage.',
    inputs: ['combined evidence'],
    produces: 'reviewed findings',
    schema: {
      type: 'object',
      required: ['accepted', 'rejected', 'coverageGaps'],
    },
  },
)
if (!reviewed) throw new Error('Verification failed')

phase('Synthesize')
const report = await agent('Produce a concise report from the reviewed findings. Return JSON.', {
  agent: 'Plan',
  label: 'Final report',
  objective: 'Return verified findings, coverage, and next actions.',
  inputs: ['reviewed findings'],
  produces: 'final report',
  schema: {
    type: 'object',
    required: ['findings', 'coverage', 'nextActions'],
  },
})
if (!report) throw new Error('Synthesis failed')

return report
```

Top-level `meta.inputs` names map to keys in the workflow tool's `args` object. For example, a plan with `inputs: ['repository']` requires this tool argument:

```javascript
args: { repository: cwd }
```

The runtime rejects non-object `args` and missing declared keys before it starts an agent.

Strict-plan rules:

- Pass every top-level `meta.inputs` value through a matching `args` key.
- Call declared phases once and in order.
- Use artifact-name arrays for `inputs`.
- Give every agent a unique `label` and a specific `objective`.
- Publish every declared phase output exactly once.
- An agent automatically publishes its `produces` value.
- Use `publish(name, value)` for JavaScript aggregates.
- Finish in the declared synthesis phase and publish its final artifact.

Use dynamic phases only when the phase graph genuinely depends on runtime findings. A declared plan is better when the dependencies are known in advance.

## Runtime API

| Global | Behavior |
|---|---|
| `agent(prompt, options)` | Runs one isolated subagent. Returns final text, parsed structured output when `schema` is set, or `null` on a recoverable failure. |
| `parallel(thunks)` | Runs functions concurrently and preserves input order. Pass functions such as `() => agent(...)`, not already-started promises. |
| `pipeline(items, ...stages)` | Runs each item through sequential stages while processing different items concurrently. A stage receives `(previousValue, originalItem, index)`. |
| `phase(title, metadata?)` | Updates workflow progress. Metadata can include `goal`, `inputs`, and `produces`. |
| `publish(name, value)` | Publishes a declared artifact from JavaScript. Available only in strict declared-plan workflows. |
| `log(message)` | Adds a workflow-level log line. |
| `parseJson(text)` | Extracts JSON from text with optional fences or surrounding prose. Prefer `schema` for agent outputs. |
| `args` | The JSON value supplied through the tool call's `args`. Strict plans require an object with every declared `meta.inputs` key. |
| `cwd` | The workflow working directory. |

Scripts use plain JavaScript. Standard globals such as `JSON`, `Math`, `Array`, and `Object` are available. TypeScript, module imports, `require`, direct filesystem APIs, network APIs, and timers are unavailable. Agents perform real work only through the tools configured for their persona.

The runtime allows up to 8 active agents and 256 agent calls per workflow.

## Choose agents and models deliberately

| Agent | Capability | Best use |
|---|---|---|
| `Explore` | Read-only, Sol model | Inventory, evidence collection, classification, repeated checks |
| `Plan` | Read-only, parent model | Evaluation, comparison, verification, synthesis |
| `General` | Read-write, parent model | Independent implementation work |

Only `General` edits files. All agents use the same working directory unless `cwd` points elsewhere. There is no automatic worktree isolation. Run `General` agents concurrently only when their file sets and side effects cannot overlap. For shared files, fan out read-only analysis and use one writer after the barrier.

The optional model tiers are `cheap` (Luna), `medium` (Terra), and `strong` (Sol). Omit `model` to use the agent's default. Use Sol for ambiguous routing, open-ended exploration, difficult implementation, final judgment, or synthesis. Use Luna for broad work only when each task is tightly specified.

There is no per-workflow token-budget parameter. Control cost with the number of calls, hard loop bounds, agent choice, model tier, and compact prompts.

## Handle partial failure honestly

Recoverable `agent()`, `parallel()`, and `pipeline()` failures return `null` and add a log entry. Script errors, invalid arguments, unknown agent names, aborts, and limit violations fail the workflow.

Do not hide missing branches with only `filter(Boolean)`. Track both completed and failed items when coverage matters:

```javascript
const results = await parallel(items.map((item) => () => agent(buildPrompt(item), {
  label: `check ${item.id}`,
  schema: resultSchema,
})))

const completed = []
const failed = []
results.forEach((result, index) => {
  if (result) completed.push(result)
  else failed.push(items[index].id)
})

return { completed, failed, total: items.length }
```

An interrupted workflow does not resume from the middle of its JavaScript program. Child sessions are stopped. Design costly workflows to be safe to rerun, keep batches bounded, and return enough coverage data to identify unfinished work.

## Final quality checklist

Before calling `workflow`, verify that:

- A workflow is more useful than direct work or a small `subagent` call.
- Every work unit has a clear prompt, evidence requirement, and output shape.
- Producers and judges are separate when independent judgment matters.
- Loops have both a success condition and a hard limit.
- Parallel writers cannot touch the same files or shared state.
- Untrusted readers cannot directly trigger high-privilege actions.
- Failed branches remain visible in the final coverage report.
- The final return value is compact, JSON-serializable, and answers the original request.
