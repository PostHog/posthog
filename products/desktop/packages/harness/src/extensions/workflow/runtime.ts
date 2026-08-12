/**
 * The workflow script sandbox: takes one JavaScript orchestration script
 * (written by the model, Claude-Code-dynamic-workflows style), runs it inside
 * a Node `vm` context, and exposes a tiny deliberate API — `agent()`,
 * `parallel()`, `pipeline()`, `phase()`, `log()`, `parseJson()`, `args`,
 * `cwd` — plus safe standard globals. Nothing else: no `require`, no `fs`,
 * no `fetch`, no timers. The only way a script touches the world is
 * `agent()`, and what that does is injected by the caller (`extension.ts`
 * wires it to the subagent package's `runAgent`), which keeps this module
 * pure and testable with a fake runner.
 *
 * Failure philosophy (borrowed from Claude Code workflows): one failed
 * `agent()`, `parallel()`, or `pipeline()` branch returns `null` and appends
 * a log line instead of killing the whole run — a 20-agent audit shouldn't
 * die because one file scan errored. Aborts are the exception: they always
 * propagate.
 *
 * SECURITY NOTE — this is a mistake-guard, not an adversarial sandbox. Node's
 * `vm` module is explicitly not a security boundary (Node's own docs say so):
 * any live value we inject (`agent`, thrown Errors, etc.) still carries a
 * prototype chain back to this module's real `Function`/`Error`/`Promise`
 * constructors, so a script that deliberately goes looking (e.g.
 * `Object.getPrototypeOf(agent).constructor(...)`) can still reach the host
 * process. We do NOT try to close that fully — doing so would need a
 * separate process or V8 isolate per workflow, which is real complexity for
 * a boundary that doesn't change the actual trust model: the script came
 * from the same orchestrating session that already has unmediated `bash`
 * access. What this sandbox *does* buy is real: it stops a script from
 * *accidentally* reaching `require`/`fs`/`fetch`/timers by only exposing the
 * few globals below, and never handing it the host's own `Array`/`Object`/
 * `JSON`/etc (see the deliberate omission in `vm.createContext` below — those
 * built-ins are provisioned natively by the context instead, precisely so
 * they don't chain back to the host realm).
 */
import * as vm from "node:vm";

export type WorkflowInputs = string[] | Record<string, string>;

export interface WorkflowPhaseMetadata {
  goal?: string;
  inputs?: string[];
  produces?: string[];
}

export interface WorkflowDeclaredPhase
  extends Required<Pick<WorkflowPhaseMetadata, "inputs" | "produces">> {
  title: string;
  goal?: string;
}

export interface WorkflowDeclaredPlan {
  name: string;
  goal?: string;
  inputs: string[];
  phases: WorkflowDeclaredPhase[];
  synthesis: { phase: string; inputs: string[]; produces: string[] };
}

export interface WorkflowArtifactStatus {
  name: string;
  phase: string;
  producer: string;
}

export interface WorkflowAgentRequest {
  /** Complete task delivered to the child, including workflow context/contracts. */
  prompt: string;
  /** Human-authored task, retained for clean status displays. */
  task: string;
  agent: string;
  label: string;
  phase?: string;
  objective?: string;
  inputs?: WorkflowInputs;
  produces?: string;
  cwd?: string;
  /** Plain JSON Schema the agent's reply must satisfy; enforced via prompt contract + parse. */
  schema?: Record<string, unknown>;
  /**
   * Opaque model request: one of the tier keywords (`"strong"`, `"medium"`,
   * `"cheap"`) or a literal bare/`"provider/id"` model id. This module has no
   * idea what any of these actually mean — it's just a string the script
   * passed through `agent()`'s `model` option; `extension.ts` is the only
   * place that knows tier keywords resolve to real model ids, keeping the
   * sandboxed runtime free of any hardcoded model knowledge.
   */
  model?: string;
}

export interface WorkflowAgentOutcome {
  /** Complete child response, used for schema parsing and validation. */
  output: string;
  /**
   * Bounded child response handed back to the workflow script when no schema
   * was requested. Keeping this separate prevents truncation from corrupting
   * an otherwise-valid structured response before it is parsed.
   */
  modelOutput?: string;
  /** Real tokens consumed by the child run (input + output). */
  tokens?: number;
}

export interface WorkflowAgentEvent extends WorkflowAgentRequest {
  /** Stable, per-workflow ID shared by task, start, and end hooks. */
  id: number;
}

export interface WorkflowHooks {
  /** Runs one subagent task to completion. Throws on failure. */
  runAgentTask: (
    event: WorkflowAgentEvent,
    signal: AbortSignal | undefined,
  ) => Promise<WorkflowAgentOutcome>;
  onPhase?: (title: string, metadata?: WorkflowPhaseMetadata) => void;
  onLog?: (message: string) => void;
  onAgentStart?: (event: WorkflowAgentEvent) => void;
  onAgentEnd?: (
    event: WorkflowAgentEvent & {
      ok: boolean;
      /** Final value handed back to the script (parsed object when schema was set). */
      result: unknown;
    },
  ) => void;
  /** Deliberately status-only: artifact values never enter UI snapshots. */
  onArtifact?: (artifact: WorkflowArtifactStatus) => void;
}

export interface WorkflowRunOptions {
  /** Names the script may pass as `{ agent }`. First entry is the default. */
  agentNames: string[];
  args?: unknown;
  cwd: string;
  signal?: AbortSignal;
  concurrency?: number;
  maxAgents?: number;
  /**
   * Milliseconds of *synchronous* script execution allowed before it's
   * forcibly terminated (`vm.Script`'s own `timeout` option). Guards against
   * an accidental busy-loop (e.g. a forgotten `await`) freezing the whole
   * host process — without this, a synchronous `while (true) {}` blocks the
   * Node event loop forever and no `AbortSignal` can help, since control
   * never returns to it. Does not bound async work (every `await` yields
   * back to the event loop, where the normal abort-signal checks apply).
   */
  syncTimeoutMs?: number;
}

export interface WorkflowRunOutcome {
  result: unknown;
  logs: string[];
  phases: string[];
  agentCount: number;
  tokensSpent: number;
}

const DEFAULT_CONCURRENCY = 8;
const DEFAULT_MAX_AGENTS = 256;
const DEFAULT_SYNC_TIMEOUT_MS = 10_000;

/**
 * Distinguishes "this script/workflow hit a hard invariant" (unknown agent
 * name, bad argument shape, resource cap, budget exhaustion) from "a
 * subagent's real-world execution failed" (network hiccup, subagent gave up,
 * schema mismatch). Only the latter should ever become a quiet `null` + log
 * line inside `parallel()`/`pipeline()` — the former means every remaining
 * item in the same fan-out is about to fail identically, so swallowing it
 * per-item just produces N confusing log lines instead of one clear,
 * actionable failure. `agent()` never synchronously throws for subagent
 * execution failures (those already resolve to `null` inside the limiter's
 * own try/catch) — every synchronous throw from `agent()`'s validation is
 * exactly the "hard invariant" case this class marks.
 */
class WorkflowFatalError extends Error {}

/**
 * Functions we hand to the sandboxed script must not expose a route back to
 * this module's real `Function` constructor via their own prototype chain
 * (`Object.getPrototypeOf(fn).constructor`) — the single laziest escape a
 * script could reach for. Stripping the prototype is cheap, real hardening;
 * it is not a full boundary (see the module-level SECURITY NOTE).
 */
function hardenExposedFunction<T extends (...args: never[]) => unknown>(
  fn: T,
): T {
  Object.setPrototypeOf(fn, null);
  return fn;
}

/**
 * Models trained on Claude Code workflows start scripts with
 * `export const meta = {...}`. `export` is illegal inside our async wrapper,
 * so demote it to a plain `const` — the metadata simply becomes a local the
 * script may reference. Also strips a wrapping Markdown fence.
 */
export function normalizeWorkflowScript(script: string): string {
  let text = script.trim();
  const fence = text.match(/^```(?:js|javascript)?\s*\n([\s\S]*?)\n?```$/i);
  if (fence) text = fence[1].trim();
  return text.replace(/^\s*export\s+(const\s+meta\b)/m, "$1");
}

/** Best-effort extraction of `meta.name` for display. Never throws. */
export function extractWorkflowName(script: string): string | undefined {
  return (
    extractDeclaredPlan(script)?.name ??
    script.match(/\bmeta\s*=\s*\{[^}]*?\bname\s*:\s*["'`]([^"'`]+)["'`]/)?.[1]
  );
}

/**
 * Reads only an object/array/string literal assigned to `meta`; it never runs
 * workflow code. A malformed or computed value intentionally means legacy
 * mode, preserving existing dynamic scripts.
 */
export function extractDeclaredPlan(
  script: string,
): WorkflowDeclaredPlan | undefined {
  const start = script.search(/\b(?:export\s+)?const\s+meta\s*=/);
  if (start < 0) return undefined;
  const equals = script.indexOf("=", start);
  const literal = readObjectLiteral(script, equals + 1);
  if (!literal) return undefined;
  try {
    const value = parseLiteral(literal) as Record<string, unknown>;
    const phases = value.phases;
    const synthesis = value.synthesis;
    if (!Array.isArray(phases) || !synthesis || typeof synthesis !== "object")
      return undefined;
    const name = stringValue(value.name);
    if (!name) return undefined;
    const parsedPhases = phases.map((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item))
        return undefined;
      const phase = item as Record<string, unknown>;
      const title = stringValue(phase.title) ?? stringValue(phase.name);
      const inputs = stringList(phase.inputs);
      const produces = stringList(phase.produces);
      return title && inputs && produces
        ? { title, goal: stringValue(phase.goal), inputs, produces }
        : undefined;
    });
    const final = synthesis as Record<string, unknown>;
    const parsedSynthesis = {
      phase: stringValue(final.phase),
      inputs: stringList(final.inputs),
      produces: stringList(final.produces),
    };
    const inputs = stringList(value.inputs) ?? [];
    if (
      parsedPhases.some((phase) => !phase) ||
      !parsedSynthesis.phase ||
      !parsedSynthesis.inputs ||
      !parsedSynthesis.produces
    )
      return undefined;
    return {
      name,
      goal: stringValue(value.goal),
      inputs,
      phases: parsedPhases as WorkflowDeclaredPhase[],
      synthesis: parsedSynthesis as WorkflowDeclaredPlan["synthesis"],
    };
  } catch {
    return undefined;
  }
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
function stringList(value: unknown): string[] | undefined {
  return Array.isArray(value) && value.every((item) => stringValue(item))
    ? value.map((item) => (item as string).trim())
    : undefined;
}
function readObjectLiteral(source: string, from: number): string | undefined {
  const first = source.slice(from).search(/\S/);
  if (first < 0 || source[from + first] !== "{") return undefined;
  const begin = from + first;
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let i = begin; i < source.length; i++) {
    const char = source[i];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      continue;
    }
    if (char === "{") depth++;
    if (char === "}" && --depth === 0) return source.slice(begin, i + 1);
  }
  return undefined;
}
/** Small literal-only parser: identifiers are accepted only as object keys. */
function parseLiteral(source: string): unknown {
  let i = 0;
  const ws = () => {
    while (/\s/.test(source[i] ?? "")) i++;
  };
  const value = (): unknown => {
    ws();
    const c = source[i];
    if (c === "{") {
      i++;
      const result: Record<string, unknown> = {};
      ws();
      while (source[i] !== "}") {
        const key = token();
        ws();
        if (source[i++] !== ":") throw new Error("literal");
        result[key] = value();
        ws();
        if (source[i] === ",") {
          i++;
          ws();
        } else if (source[i] !== "}") throw new Error("literal");
      }
      i++;
      return result;
    }
    if (c === "[") {
      i++;
      const result: unknown[] = [];
      ws();
      while (source[i] !== "]") {
        result.push(value());
        ws();
        if (source[i] === ",") {
          i++;
          ws();
        } else if (source[i] !== "]") throw new Error("literal");
      }
      i++;
      return result;
    }
    if (c === "'" || c === '"') return string();
    throw new Error("non-literal");
  };
  const string = () => {
    const q = source[i++];
    let out = "";
    while (i < source.length && source[i] !== q) {
      if (source[i] === "\\") i++;
      out += source[i++];
    }
    if (source[i++] !== q) throw new Error("string");
    return out;
  };
  const token = () => {
    ws();
    if (source[i] === "'" || source[i] === '"') return string();
    const match = source.slice(i).match(/^[A-Za-z_$][\w$]*/);
    if (!match) throw new Error("key");
    i += match[0].length;
    return match[0];
  };
  const result = value();
  ws();
  if (i !== source.length) throw new Error("trailing");
  return result;
}

/**
 * Finds statically named phase calls before the script begins. This lets the
 * status UI show the workflow's upcoming shape rather than only phases which
 * have already started. Dynamic phase names remain supported at runtime, but
 * cannot be known in advance.
 */
export function extractWorkflowPhases(script: string): string[] {
  return extractWorkflowPhaseMetadata(script).map((phase) => phase.title);
}

/** Best-effort metadata for literal `phase('title', { ... })` calls. */
export function extractWorkflowPhaseMetadata(
  script: string,
): Array<{ title: string; metadata?: WorkflowPhaseMetadata }> {
  const phases: Array<{ title: string; metadata?: WorkflowPhaseMetadata }> = [];
  // Static extraction is intentionally conservative: dynamic scripts still get
  // their complete metadata when phase() executes at runtime.
  const pattern =
    /\bphase\s*\(\s*(["'`])([^"'`]+)\1(?:\s*,\s*\{([\s\S]*?)\})?\s*\)/g;
  for (const match of script.matchAll(pattern)) {
    const title = match[2]?.trim();
    if (!title || phases.some((phase) => phase.title === title)) continue;
    const metadata = parseStaticPhaseMetadata(match[3]);
    phases.push({ title, ...(metadata ? { metadata } : {}) });
  }
  return phases;
}

function parseStaticPhaseMetadata(
  source: string | undefined,
): WorkflowPhaseMetadata | undefined {
  if (!source) return undefined;
  const goal = source.match(/\bgoal\s*:\s*(["'`])([^"'`]+)\1/)?.[2]?.trim();
  const list = (key: string): string[] | undefined => {
    const body = source.match(
      new RegExp(`\\b${key}\\s*:\\s*\\[([^\\]]*)\\]`),
    )?.[1];
    if (body === undefined) return undefined;
    const values = [...body.matchAll(/(["'`])([^"'`]+)\1/g)]
      .map((item) => item[2]?.trim())
      .filter((item): item is string => Boolean(item));
    return values.length > 0 ? values : undefined;
  };
  const metadata = { goal, inputs: list("inputs"), produces: list("produces") };
  return metadata.goal || metadata.inputs || metadata.produces
    ? metadata
    : undefined;
}

function validateDeclaredPlan(plan: WorkflowDeclaredPlan): void {
  const names = new Set<string>();
  const available = new Set(plan.inputs);
  for (const phase of plan.phases) {
    if (names.has(phase.title))
      throw new WorkflowFatalError(
        `strict plan has duplicate phase "${phase.title}"`,
      );
    names.add(phase.title);
    for (const input of phase.inputs)
      if (!available.has(input))
        throw new WorkflowFatalError(
          `phase "${phase.title}" requires "${input}" before any declared producer`,
        );
    for (const output of phase.produces) {
      if (available.has(output))
        throw new WorkflowFatalError(
          `strict plan has duplicate artifact "${output}"`,
        );
      available.add(output);
    }
  }
  if (plan.phases.at(-1)?.title !== plan.synthesis.phase)
    throw new WorkflowFatalError(
      "strict plan synthesis.phase must be the final declared phase",
    );
  for (const input of plan.synthesis.inputs)
    if (!available.has(input))
      throw new WorkflowFatalError(
        `synthesis requires unknown artifact "${input}"`,
      );
  for (const output of plan.synthesis.produces)
    if (!plan.phases.at(-1)?.produces.includes(output))
      throw new WorkflowFatalError(
        `synthesis artifact "${output}" must be produced by its final phase`,
      );
}

function currentDeclaredPhase(
  plan: WorkflowDeclaredPlan,
  index: number,
): WorkflowDeclaredPhase {
  const phase = plan.phases[index];
  if (!phase)
    throw new WorkflowFatalError(
      "strict plan requires phase() before agent() or publish()",
    );
  return phase;
}

function ensurePhaseArtifacts(
  phase: WorkflowDeclaredPhase,
  artifacts: Map<string, unknown>,
): void {
  const missing = phase.produces.filter((name) => !artifacts.has(name));
  if (missing.length)
    throw new WorkflowFatalError(
      `phase "${phase.title}" did not publish declared artifact(s): ${missing.join(", ")}`,
    );
}

function publishArtifact(
  name: string,
  value: unknown,
  phase: WorkflowDeclaredPhase,
  producer: string,
  artifacts: Map<string, { value: unknown; phase: string; producer: string }>,
  hooks: WorkflowHooks,
): void {
  if (!phase.produces.includes(name))
    throw new WorkflowFatalError(
      `artifact "${name}" is not declared for phase "${phase.title}"`,
    );
  if (artifacts.has(name))
    throw new WorkflowFatalError(`artifact "${name}" was already published`);
  artifacts.set(name, { value, phase: phase.title, producer });
  hooks.onArtifact?.({ name, phase: phase.title, producer });
}

function buildArtifactContext(
  inputs: string[],
  artifacts: Map<string, { value: unknown }>,
  args: unknown,
): string | undefined {
  const values = Object.fromEntries(
    inputs.map((name) => [
      name,
      artifacts.get(name)?.value ??
        (args && typeof args === "object"
          ? (args as Record<string, unknown>)[name]
          : undefined),
    ]),
  );
  return `Artifact inputs (use these exact values):\n${JSON.stringify(values, null, 2)}`;
}

/** Minimal concurrency gate; `runPool` wants a fixed array, but workflow scripts schedule dynamically. */
function createLimiter(limit: number) {
  let active = 0;
  const queue: Array<() => void> = [];
  return async <T>(fn: () => Promise<T>): Promise<T> => {
    if (active >= limit)
      await new Promise<void>((resolve) => queue.push(resolve));
    active++;
    try {
      return await fn();
    } finally {
      active--;
      queue.shift()?.();
    }
  };
}

/**
 * Throws `WorkflowFatalError`, not a plain `TypeError`: every call site is
 * validating an argument the *script* passed to one of our own API
 * functions (`phase()`, `agent()`), so a bad value here is a script bug, not
 * a subagent's real-world failure — it must never be silently swallowed
 * into a `null` + log line by `parallel()`/`pipeline()` (see
 * `WorkflowFatalError`'s own comment).
 */
function requireString(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim())
    throw new WorkflowFatalError(`${name} must be a non-empty string`);
  return value.trim();
}

function optionalString(value: unknown, name: string): string | undefined {
  return value === undefined ? undefined : requireString(value, name);
}

function requireStringList(value: unknown, name: string): string[] {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || !item.trim())
  )
    throw new WorkflowFatalError(
      `${name} must be an array of non-empty strings`,
    );
  return value.map((item) => item.trim());
}

function validateInputs(value: unknown): WorkflowInputs {
  if (Array.isArray(value)) return requireStringList(value, "agent inputs");
  if (value === null || typeof value !== "object")
    throw new WorkflowFatalError(
      "agent inputs must be an array of strings or a record of string values",
    );
  const entries = Object.entries(value);
  if (
    entries.some(
      ([key, item]) => !key.trim() || typeof item !== "string" || !item.trim(),
    )
  )
    throw new WorkflowFatalError(
      "agent inputs record keys and values must be non-empty strings",
    );
  return Object.fromEntries(
    entries.map(([key, item]) => [key.trim(), item.trim() as string]),
  );
}

function validatePhaseMetadata(
  value: unknown,
): WorkflowPhaseMetadata | undefined {
  if (value === undefined) return undefined;
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new WorkflowFatalError("phase metadata must be an object");
  const metadata = value as Record<string, unknown>;
  return {
    goal: optionalString(metadata.goal, "phase goal"),
    inputs:
      metadata.inputs === undefined
        ? undefined
        : requireStringList(metadata.inputs, "phase inputs"),
    produces:
      metadata.produces === undefined
        ? undefined
        : requireStringList(metadata.produces, "phase produces"),
  };
}

function buildWorkflowContext(
  request: Pick<WorkflowAgentRequest, "objective" | "inputs" | "produces">,
): string | undefined {
  const lines: string[] = [];
  if (request.objective) lines.push(`- Objective: ${request.objective}`);
  if (request.inputs) {
    const inputs = Array.isArray(request.inputs)
      ? request.inputs
      : Object.entries(request.inputs).map(
          ([name, value]) => `${name}: ${value}`,
        );
    lines.push(`- Inputs: ${inputs.join("; ")}`);
  }
  if (request.produces) lines.push(`- Produces: ${request.produces}`);
  return lines.length > 0
    ? ["Workflow context:", ...lines].join("\n")
    : undefined;
}

/** Parses JSON out of an agent's text reply, tolerating fences and prose around it. */
export function parseJsonLoose(text: unknown): unknown {
  if (typeof text !== "string")
    throw new TypeError("parseJson() expects a string");
  const trimmed = text.trim();
  const fence = trimmed.match(/```(?:json)?\s*\n([\s\S]*?)\n\s*```/i);
  const body = (fence ? fence[1] : trimmed).trim();
  try {
    return JSON.parse(body);
  } catch {
    // Fall back to the outermost bracketed region.
    const start = body.search(/[[{]/);
    const end = Math.max(body.lastIndexOf("}"), body.lastIndexOf("]"));
    if (start >= 0 && end > start)
      return JSON.parse(body.slice(start, end + 1));
    throw new Error("parseJson(): no JSON found in agent output");
  }
}

/**
 * Shallow validation of a parsed value against the JSON Schema the script
 * passed to `agent()`: top-level type plus required keys. Deliberately not a
 * full JSON Schema validator — the schema's main job is being embedded in
 * the prompt as an output contract; this check just catches an agent that
 * ignored the contract entirely, so the failure surfaces as null + log
 * instead of a confusing downstream TypeError.
 */
export function checkAgainstSchema(
  value: unknown,
  schema: Record<string, unknown>,
): void {
  if (schema.type === "object") {
    if (value === null || typeof value !== "object" || Array.isArray(value))
      throw new Error("agent output did not match schema: expected an object");
    if (Array.isArray(schema.required)) {
      const missing = schema.required.filter(
        (key) => typeof key === "string" && !(key in (value as object)),
      );
      if (missing.length > 0)
        throw new Error(
          `agent output did not match schema: missing required key(s) ${missing.join(", ")}`,
        );
    }
  } else if (schema.type === "array" && !Array.isArray(value)) {
    throw new Error("agent output did not match schema: expected an array");
  }
}

function buildSchemaContract(schema: Record<string, unknown>): string {
  return [
    "Output contract:",
    "- Reply with ONLY a single JSON value matching this JSON Schema — no prose before or after it.",
    "- Do your reading/investigation first, then produce the JSON as your final answer.",
    JSON.stringify(schema, null, 2),
  ].join("\n");
}

export async function runWorkflowScript(
  script: string,
  options: WorkflowRunOptions,
  hooks: WorkflowHooks,
): Promise<WorkflowRunOutcome> {
  const body = normalizeWorkflowScript(script);
  const plan = extractDeclaredPlan(script);
  if (plan) validateDeclaredPlan(plan);
  const artifacts = new Map<
    string,
    { value: unknown; phase: string; producer: string }
  >();
  let declaredPhaseIndex = -1;
  const maxAgents = options.maxAgents ?? DEFAULT_MAX_AGENTS;
  const limiter = createLimiter(
    Math.max(1, options.concurrency ?? DEFAULT_CONCURRENCY),
  );
  const validAgents = new Set(options.agentNames);
  const defaultAgent = options.agentNames[0];
  if (!defaultAgent) throw new Error("workflow requires at least one agent");

  const logs: string[] = [];
  const phases: string[] = [];
  let currentPhase: string | undefined;
  let agentCount = 0;
  let tokensSpent = 0;
  const pending = new Set<Promise<unknown>>();

  const throwIfAborted = () => {
    if (options.signal?.aborted) throw new Error("Workflow was aborted");
  };

  const log = (message: unknown) => {
    const text = String(message);
    logs.push(text);
    hooks.onLog?.(text);
  };

  const phase = (title: unknown, metadataValue: unknown = undefined) => {
    const text = requireString(title, "phase title");
    const metadata = validatePhaseMetadata(metadataValue);
    if (plan) {
      const next = plan.phases[declaredPhaseIndex + 1];
      if (!next || next.title !== text)
        throw new WorkflowFatalError(
          `strict plan requires phase "${next?.title ?? "(none)"}" next, received "${text}"`,
        );
      if (declaredPhaseIndex >= 0)
        ensurePhaseArtifacts(plan.phases[declaredPhaseIndex], artifacts);
      declaredPhaseIndex++;
    }
    currentPhase = text;
    if (!phases.includes(text)) phases.push(text);
    hooks.onPhase?.(text, metadata);
  };

  const publish = (name: unknown, value: unknown) => {
    const artifact = requireString(name, "artifact name");
    if (!plan)
      throw new WorkflowFatalError(
        "publish() is available only in a literal meta.phases workflow",
      );
    const phase = currentDeclaredPhase(plan, declaredPhaseIndex);
    publishArtifact(artifact, value, phase, "workflow", artifacts, hooks);
    return value;
  };

  const agent = (prompt: unknown, agentOptions: unknown = {}) => {
    throwIfAborted();
    const taskPrompt = requireString(prompt, "agent prompt");
    if (agentOptions === null || typeof agentOptions !== "object")
      throw new WorkflowFatalError("agent options must be an object");
    const opts = agentOptions as {
      label?: unknown;
      agent?: unknown;
      cwd?: unknown;
      schema?: unknown;
      model?: unknown;
      objective?: unknown;
      inputs?: unknown;
      produces?: unknown;
    };
    const agentName =
      opts.agent === undefined
        ? defaultAgent
        : requireString(opts.agent, "agent name");
    if (!validAgents.has(agentName)) {
      throw new WorkflowFatalError(
        `Unknown agent "${agentName}". Available: ${options.agentNames.join(", ")}`,
      );
    }
    let schema: Record<string, unknown> | undefined;
    if (opts.schema !== undefined) {
      if (
        opts.schema === null ||
        typeof opts.schema !== "object" ||
        Array.isArray(opts.schema)
      )
        throw new WorkflowFatalError(
          "agent schema must be a plain JSON Schema object, e.g. { type: 'object', required: [...], properties: {...} }",
        );
      schema = opts.schema as Record<string, unknown>;
    }
    agentCount++;
    if (agentCount > maxAgents)
      throw new WorkflowFatalError(
        `workflow agent limit reached (${maxAgents})`,
      );
    const id = agentCount;
    // Capture phase ownership at dispatch. A child runs behind the concurrency
    // limiter and may complete after the script has advanced its phase state.
    let producerPhase: WorkflowDeclaredPhase | undefined;
    if (plan) {
      const declared = currentDeclaredPhase(plan, declaredPhaseIndex);
      producerPhase = declared;
      if (!Array.isArray(opts.inputs))
        throw new WorkflowFatalError(
          "strict-plan agent inputs must be an array of artifact names",
        );
      const inputNames = validateInputs(opts.inputs);
      if (!Array.isArray(inputNames))
        throw new WorkflowFatalError(
          "strict-plan agent inputs must be artifact names",
        );
      for (const name of inputNames) {
        if (!plan.inputs.includes(name) && !artifacts.has(name))
          throw new WorkflowFatalError(
            `artifact "${name}" is unavailable before phase "${declared.title}"`,
          );
      }
      const produced = optionalString(opts.produces, "agent produces");
      if (!produced || !declared.produces.includes(produced))
        throw new WorkflowFatalError(
          `strict-plan agent must produce a declared artifact for phase "${declared.title}"`,
        );
    }
    const request: WorkflowAgentRequest = {
      task: taskPrompt,
      prompt: taskPrompt,
      agent: agentName,
      label:
        typeof opts.label === "string" && opts.label.trim()
          ? opts.label.trim()
          : `agent ${id}`,
      phase: currentPhase,
      cwd: opts.cwd === undefined ? undefined : requireString(opts.cwd, "cwd"),
      schema,
      objective: optionalString(opts.objective, "agent objective"),
      inputs:
        opts.inputs === undefined ? undefined : validateInputs(opts.inputs),
      produces: optionalString(opts.produces, "agent produces"),
      model:
        opts.model === undefined
          ? undefined
          : requireString(opts.model, "model"),
    };
    const contextBlock = buildWorkflowContext(request);
    const artifactBlock =
      plan && Array.isArray(request.inputs)
        ? buildArtifactContext(request.inputs, artifacts, options.args)
        : undefined;
    request.prompt = [
      request.task,
      contextBlock,
      artifactBlock,
      schema ? buildSchemaContract(schema) : undefined,
    ]
      .filter((part): part is string => Boolean(part))
      .join("\n\n");

    const run = limiter(async () => {
      throwIfAborted();
      const event: WorkflowAgentEvent = { id, ...request };
      hooks.onAgentStart?.(event);
      try {
        const outcome = await hooks.runAgentTask(event, options.signal);
        throwIfAborted();
        tokensSpent += outcome.tokens ?? 0;
        // Named artifacts must retain their complete value for downstream
        // consumers. Legacy free-text workflows keep their bounded handoff.
        let result: unknown = plan
          ? outcome.output
          : (outcome.modelOutput ?? outcome.output);
        if (schema) {
          result = parseJsonLoose(outcome.output);
          checkAgainstSchema(result, schema);
        }
        if (event.produces && producerPhase) {
          publishArtifact(
            event.produces,
            result,
            producerPhase,
            event.label,
            artifacts,
            hooks,
          );
        }
        hooks.onAgentEnd?.({ ...event, ok: true, result });
        return result;
      } catch (error) {
        if (options.signal?.aborted) throw error;
        log(
          `agent "${request.label}" failed: ${error instanceof Error ? error.message : String(error)}`,
        );
        hooks.onAgentEnd?.({ ...event, ok: false, result: null });
        return null;
      }
    });
    pending.add(run);
    run.finally(() => pending.delete(run)).catch(() => {});
    return run;
  };

  const parallel = async (thunks: unknown) => {
    throwIfAborted();
    if (!Array.isArray(thunks) || thunks.some((t) => typeof t !== "function")) {
      throw new TypeError(
        "parallel() expects an array of functions, not promises. Wrap each call: () => agent(...)",
      );
    }
    return Promise.all(
      thunks.map(async (thunk, index) => {
        try {
          return await (thunk as () => Promise<unknown>)();
        } catch (error) {
          if (options.signal?.aborted || error instanceof WorkflowFatalError)
            throw error;
          log(
            `parallel[${index}] failed: ${error instanceof Error ? error.message : String(error)}`,
          );
          return null;
        }
      }),
    );
  };

  /**
   * Fans `items` out through sequential `stages`; different items run
   * concurrently, but each item's stages run in order. Each stage receives
   * (previousValue, originalItem, index). A stage failure nulls out that
   * item's slot and logs it; other items continue.
   */
  const pipeline = async (
    items: unknown,
    ...stages: Array<
      (prev: unknown, original: unknown, index: number) => unknown
    >
  ) => {
    throwIfAborted();
    if (!Array.isArray(items))
      throw new TypeError("pipeline() expects an array as its first argument");
    if (stages.length === 0 || stages.some((s) => typeof s !== "function"))
      throw new TypeError(
        "pipeline() stages must be functions: pipeline(items, item => agent(...), result => ...)",
      );
    return Promise.all(
      items.map(async (item, index) => {
        let value: unknown = item;
        for (const stage of stages) {
          try {
            throwIfAborted();
            value = await stage(value, item, index);
          } catch (error) {
            if (options.signal?.aborted || error instanceof WorkflowFatalError)
              throw error;
            log(
              `pipeline[${index}] failed: ${error instanceof Error ? error.message : String(error)}`,
            );
            return null;
          }
        }
        return value;
      }),
    );
  };

  // Deliberately do NOT pass the host's own `JSON`/`Math`/`Array`/`Object`/etc
  // into this object: `vm.createContext()` already provisions a full,
  // context-native set of built-ins for any code it runs. Handing over our
  // own host-realm versions instead would make `Array.constructor(...)` (or
  // any other built-in) a one-line escape straight to this process's real
  // `Function` constructor — no gadget-hunting required. Only the
  // *custom* bridge functions below are intentionally host-realm (they have
  // to be, to do real work), and those are hardened by `hardenExposedFunction`.
  const context = vm.createContext({
    agent: hardenExposedFunction(agent),
    parallel: hardenExposedFunction(parallel),
    pipeline: hardenExposedFunction(pipeline),
    phase: hardenExposedFunction(phase),
    log: hardenExposedFunction(log),
    parseJson: hardenExposedFunction(parseJsonLoose),
    publish: hardenExposedFunction(publish),
    args: options.args,
    cwd: options.cwd,
    console: Object.freeze({
      log,
      info: log,
      warn: hardenExposedFunction((m: unknown) => log(`[warn] ${String(m)}`)),
      error: hardenExposedFunction((m: unknown) => log(`[error] ${String(m)}`)),
    }),
  });

  try {
    const wrapped = `(async () => {\n${body}\n})()`;
    let compiled: vm.Script;
    try {
      compiled = new vm.Script(wrapped, { filename: "workflow.js" });
    } catch (error) {
      throw new Error(decorateSyntaxError(error, body));
    }
    const result: unknown = await compiled.runInContext(context, {
      timeout: options.syncTimeoutMs ?? DEFAULT_SYNC_TIMEOUT_MS,
    });
    throwIfAborted();
    assertJsonSerializable(result, "workflow result");
    if (plan) {
      if (declaredPhaseIndex !== plan.phases.length - 1)
        throw new WorkflowFatalError(
          "strict plan did not activate every declared phase",
        );
      ensurePhaseArtifacts(plan.phases[declaredPhaseIndex], artifacts);
      if (plan.synthesis.phase !== currentPhase)
        throw new WorkflowFatalError(
          `strict plan must finish in synthesis phase "${plan.synthesis.phase}"`,
        );
      for (const artifact of plan.synthesis.produces) {
        const published = artifacts.get(artifact);
        if (!published || published.phase !== plan.synthesis.phase)
          throw new WorkflowFatalError(
            `synthesis artifact "${artifact}" was not published by its declared final phase`,
          );
      }
    }
    return { result, logs, phases, agentCount, tokensSpent };
  } finally {
    // Never leave child pi processes running unobserved after the script
    // settles (e.g. it returned without awaiting, or threw mid-fan-out).
    await Promise.allSettled([...pending]);
  }
}

/** Turns the VM's bare SyntaxError into an actionable message for the model. */
function decorateSyntaxError(error: unknown, body: string): string {
  const message = error instanceof Error ? error.message : String(error);
  // V8's compile stack begins with the filename, source line, and caret.
  // Keep that small excerpt: the message alone cannot identify which of many
  // inline agent options or schemas has an unmatched delimiter.
  const location =
    error instanceof Error && error.stack
      ? error.stack.split("\n").slice(0, 4).join("\n")
      : message;
  const hints: string[] = [];
  if (/^\s*(export|import)\b/m.test(body)) {
    hints.push(
      "workflow scripts are plain scripts, not modules: remove import/export statements (only `export const meta = {...}` is tolerated, and it is rewritten to a plain const)",
    );
  }
  if (/:\s*(string|number|boolean|unknown|any)\b|\bas\s+const\b/.test(body)) {
    hints.push("use plain JavaScript, not TypeScript syntax");
  }
  return [
    "workflow script syntax error:",
    location,
    ...hints.map((hint) => `Hint: ${hint}`),
  ].join("\n");
}

/**
 * Two independent, complementary checks — neither alone is enough:
 *
 *  - `structuredClone` throws on values that are almost always an *accidental
 *    mistake*: an un-awaited `Promise` (forgot to `await agent()`), a
 *    `Function`, a `WeakMap`/`WeakSet`. This is the original, most common
 *    failure mode this check exists for.
 *  - `structuredClone` does NOT throw on circular references or `BigInt` —
 *    both are "cloneable" but neither survives `JSON.stringify`, which this
 *    module's own summary text (and, more importantly, whatever downstream
 *    transport eventually serializes the tool's `details` payload) needs.
 *
 * Catching both here, synchronously, with a clear message beats a cryptic
 * "Converting circular structure to JSON" surfacing later out of context —
 * or reaching a serialization boundary we don't control at all.
 */
function assertJsonSerializable(value: unknown, name: string): void {
  try {
    structuredClone(value);
  } catch (error) {
    const detail = error instanceof Error ? ` ${error.message}` : "";
    throw new Error(
      `${name} must be JSON-serializable; did you forget to await agent(), parallel(), or pipeline()?${detail}`,
    );
  }
  try {
    JSON.stringify(value);
  } catch (error) {
    const detail = error instanceof Error ? ` ${error.message}` : "";
    throw new Error(
      `${name} must be JSON-serializable (no circular references, no BigInt).${detail}`,
    );
  }
}
