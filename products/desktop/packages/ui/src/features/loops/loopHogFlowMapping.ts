import type { Schemas } from "@posthog/api-client/generated";
import {
  type HogFlowLoopBody,
  type HogFlowScheduleWrite,
  LOOPS_ORIGIN_PRODUCT,
} from "@posthog/api-client/hogFlowLoops";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { defaultLoopBehaviors, type LoopFormValues } from "./loopFormTypes";
import {
  hogFlowScheduleToScheduleConfig,
  scheduleConfigToHogFlowSchedule,
} from "./loopScheduleRRule";

export const CREATE_TASK_TEMPLATE_ID = "template-posthog-create-task";
const GITHUB_EVENT_RECEIVED_EVENT = "$github_event_received";

const TRIGGER_ACTION_ID = "trigger";
const TASK_ACTION_ID = "create_task";
const EXIT_ACTION_ID = "exit";

const LOOP_GITHUB_EVENTS: ReadonlySet<string> =
  new Set<LoopSchemas.LoopGithubTriggerEventEnum>([
    "issues",
    "issue_comment",
    "pull_request",
    "push",
  ]);

/** Thrown when the form holds a trigger the workflow shape cannot carry. The
 * form's own validation stops this before submit; the error is the backstop. */
export class UnsupportedLoopShapeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UnsupportedLoopShapeError";
  }
}

export interface LoopHogFlowWrite {
  flow: HogFlowLoopBody;
  /** Null for a GitHub-triggered loop, which has no schedule row. */
  schedule: HogFlowScheduleWrite | null;
}

/** The fields the mapper reads. Both the list row (`HogFlowMinimal`) and the
 * detail (`HogFlow`) satisfy it; only the detail carries `schedules`. */
export interface LoopHogFlowSource {
  id: string;
  name?: string | null;
  description?: string;
  status?: Schemas.HogFlowStateEnum;
  created_at: string;
  updated_at: string;
  created_by?: { id: number } | null;
  actions?: unknown;
  edges?: unknown;
  schedules?: Schemas.HogFlowSchedule[];
  /** Staged edits the workflow editor holds back from the live graph. Only
   * the detail carries it; a list row leaves it undefined. */
  draft?: unknown;
  draft_updated_at?: string | null;
}

/** Task inputs the form owns. Anything else on the step is left as found. */
const MANAGED_TASK_INPUTS: ReadonlySet<string> = new Set([
  "prompt",
  "repository",
  "model",
  "skills",
]);

type Json = Record<string, unknown>;

function isRecord(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function inputValue(inputs: Json, key: string): unknown {
  const input = inputs[key];
  return isRecord(input) ? input.value : undefined;
}

function exactFilter(key: string, value: string[]): Json {
  return { key, value, operator: "exact", type: "event" };
}

function githubTriggerConfig(
  config: LoopSchemas.LoopGithubTriggerConfig,
): Json {
  // Only people with write access can start a run: the event body reaches an
  // AI task that acts with the owner's access, so a drive-by issue or comment
  // must not be able to steer it. Same gate the loops webhook applied.
  const properties = [
    exactFilter("repository", [config.repository]),
    exactFilter("event_type", config.events),
    exactFilter("actor_access", ["write"]),
  ];
  const actions = config.filters?.actions ?? [];
  if (actions.length > 0) {
    properties.push(exactFilter("action", actions));
  }
  return {
    type: "internal-event",
    filters: {
      source: "internal-events",
      events: [{ id: GITHUB_EVENT_RECEIVED_EVENT, type: "events" }],
      properties,
    },
  };
}

function triggerFromForm(values: LoopFormValues): {
  config: Json;
  schedule: HogFlowScheduleWrite | null;
} {
  const enabledTriggers = values.triggers.filter((trigger) => trigger.enabled);
  if (enabledTriggers.length !== 1) {
    throw new UnsupportedLoopShapeError(
      "A workflow-backed loop has exactly one trigger.",
    );
  }
  const trigger = enabledTriggers[0];
  if (trigger.type === "schedule") {
    const schedule = scheduleConfigToHogFlowSchedule(
      trigger.config as LoopSchemas.LoopScheduleTriggerConfig,
    );
    if (!schedule) {
      throw new UnsupportedLoopShapeError(
        "This schedule is not one of the supported presets.",
      );
    }
    return { config: { type: "schedule" }, schedule };
  }
  if (trigger.type === "github") {
    const config = trigger.config as LoopSchemas.LoopGithubTriggerConfig;
    return { config: githubTriggerConfig(config), schedule: null };
  }
  throw new UnsupportedLoopShapeError(
    `Trigger type "${trigger.type}" is not supported for workflow-backed loops.`,
  );
}

function taskInputs(values: LoopFormValues): Json {
  const inputs: Json = { prompt: { value: values.instructions.trim() } };
  const repository = values.repositories[0]?.full_name;
  if (repository) {
    inputs.repository = { value: repository };
  }
  const model = values.model.trim();
  if (model) {
    inputs.model = {
      value: {
        model,
        ...(values.reasoningEffort
          ? { reasoning_effort: values.reasoningEffort }
          : {}),
      },
    };
  }
  if (values.teamSkills.length > 0) {
    inputs.skills = { value: [...values.teamSkills] };
  }
  return inputs;
}

/** Task inputs on an existing flow that the form does not manage, so a save
 * keeps what the workflow editor added (connectors, parallelism, a title). */
function preservedTaskInputs(existing: ParsedLoopActions | null): Json {
  if (!existing) return {};
  return Object.fromEntries(
    Object.entries(existing.taskInputs).filter(
      ([key]) => !MANAGED_TASK_INPUTS.has(key),
    ),
  );
}

/** One of the three steps the loop form draws, as the API holds it. */
interface LoopAction extends Schemas.HogFlowAction {
  type: "trigger" | "function" | "exit";
  config: Json;
}

function isLoopAction(value: unknown): value is LoopAction {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    isRecord(value.config) &&
    (value.type === "trigger" ||
      value.type === "function" ||
      value.type === "exit")
  );
}

const DEFAULT_TRIGGER_ACTION: LoopAction = {
  id: TRIGGER_ACTION_ID,
  name: "Trigger",
  type: "trigger",
  config: {},
};

const DEFAULT_TASK_ACTION: LoopAction = {
  id: TASK_ACTION_ID,
  name: "Create AI task",
  type: "function",
  config: {},
};

const DEFAULT_EXIT_ACTION: LoopAction = {
  id: EXIT_ACTION_ID,
  name: "Exit",
  type: "exit",
  config: { reason: "Task created" },
};

/**
 * The workflow a loop form saves as: one trigger, one "Create AI task" step,
 * one exit. `enabled` decides whether the flow is created live or as a draft.
 * Pass `existing` on an edit: the save then only replaces the fields the form
 * owns (the trigger config, the task template and inputs), so step names,
 * skip filters and error handling set in the workflow editor survive.
 */
export function formValuesToHogFlowWrite(
  values: LoopFormValues,
  options: { enabled: boolean; existing?: LoopHogFlowSource },
): LoopHogFlowWrite {
  const trigger = triggerFromForm(values);
  const existing = options.existing
    ? parseLoopActions(options.existing.actions)
    : null;
  const triggerAction = existing?.actions.trigger ?? DEFAULT_TRIGGER_ACTION;
  const taskAction = existing?.actions.task ?? DEFAULT_TASK_ACTION;
  const exitAction = existing?.actions.exit ?? DEFAULT_EXIT_ACTION;
  return {
    flow: {
      name: values.name.trim(),
      description: values.description.trim(),
      status: options.enabled ? "active" : "draft",
      origin_product: LOOPS_ORIGIN_PRODUCT,
      exit_condition: "exit_only_at_end",
      actions: [
        { ...triggerAction, config: trigger.config },
        {
          ...taskAction,
          config: {
            ...taskAction.config,
            template_id: CREATE_TASK_TEMPLATE_ID,
            inputs: {
              ...preservedTaskInputs(existing),
              ...taskInputs(values),
            },
          },
        },
        exitAction,
      ],
      edges: [
        { from: triggerAction.id, to: taskAction.id, type: "continue" },
        { from: taskAction.id, to: exitAction.id, type: "continue" },
      ],
    },
    schedule: trigger.schedule,
  };
}

interface ParsedLoopActions {
  trigger: Json;
  taskInputs: Json;
  actions: { trigger: LoopAction; task: LoopAction; exit: LoopAction | null };
}

/** The trigger and task step of a loop-shaped graph, or null when the graph
 * holds anything the loop form did not put there. */
function parseLoopActions(actions: unknown): ParsedLoopActions | null {
  if (!Array.isArray(actions)) return null;
  let trigger: LoopAction | null = null;
  let task: LoopAction | null = null;
  let exit: LoopAction | null = null;
  for (const action of actions) {
    if (!isLoopAction(action)) return null;
    if (action.type === "trigger") {
      if (trigger) return null;
      trigger = action;
    } else if (action.type === "function") {
      if (task || action.config.template_id !== CREATE_TASK_TEMPLATE_ID) {
        return null;
      }
      task = action;
    } else {
      if (exit) return null;
      exit = action;
    }
  }
  if (!trigger || !task) return null;
  return {
    trigger: trigger.config,
    taskInputs: isRecord(task.config.inputs) ? task.config.inputs : {},
    actions: { trigger, task, exit },
  };
}

/** Whether the edges are exactly the straight line the form draws:
 * trigger to task, then task to exit. A branch or a loop back would be lost
 * when a save rewrites the edges. */
function hasLoopShapedEdges(
  edges: unknown,
  actions: ParsedLoopActions["actions"],
): boolean {
  if (edges === undefined || edges === null) return true;
  if (!Array.isArray(edges)) return false;
  const ids = {
    trigger: actions.trigger.id,
    task: actions.task.id,
    exit: actions.exit?.id ?? null,
  };
  const expected = [
    `${ids.trigger}>${ids.task}`,
    ...(ids.exit ? [`${ids.task}>${ids.exit}`] : []),
  ];
  const actual = edges.map((edge) =>
    isRecord(edge) && edge.type === "continue"
      ? `${edge.from}>${edge.to}`
      : "?",
  );
  return (
    actual.length === expected.length &&
    expected.every((edge) => actual.includes(edge))
  );
}

function filterValues(filter: Json): string[] | null {
  if (filter.operator !== "exact") return null;
  const raw = Array.isArray(filter.value) ? filter.value : [filter.value];
  if (!raw.every((value): value is string => typeof value === "string")) {
    return null;
  }
  return raw;
}

function githubConfigFromTrigger(
  trigger: Json,
): LoopSchemas.LoopGithubTriggerConfig | null {
  if (!isRecord(trigger.filters)) return null;
  const { events, properties } = trigger.filters;
  const subscribed =
    Array.isArray(events) &&
    events.length === 1 &&
    isRecord(events[0]) &&
    events[0].id === GITHUB_EVENT_RECEIVED_EVENT;
  if (!subscribed) return null;

  let repository: string | null = null;
  let eventTypes: string[] | null = null;
  let actions: string[] = [];
  let trustedActorsOnly = false;
  for (const property of Array.isArray(properties) ? properties : []) {
    if (!isRecord(property)) return null;
    const values = filterValues(property);
    if (!values) return null;
    switch (property.key) {
      case "actor_access":
        if (values.length !== 1 || values[0] !== "write") return null;
        trustedActorsOnly = true;
        break;
      case "repository":
        if (values.length !== 1) return null;
        repository = values[0];
        break;
      case "event_type":
        if (!values.every((value) => LOOP_GITHUB_EVENTS.has(value))) {
          return null;
        }
        eventTypes = values;
        break;
      case "action":
        actions = values;
        break;
      default:
        return null;
    }
  }
  // The form picks one event type; two would open as an invalid form.
  if (!repository || !eventTypes || eventTypes.length !== 1) return null;
  // A trigger open to anyone is outside what a loop offers; editing it here
  // would silently narrow it back to write access.
  if (!trustedActorsOnly) return null;
  return {
    github_integration_id: 0,
    repository,
    events: eventTypes as LoopSchemas.LoopGithubTriggerEventEnum[],
    ...(actions.length > 0 ? { filters: { actions } } : {}),
  };
}

function scheduleConfigFromFlow(
  schedules: Schemas.HogFlowSchedule[] | undefined,
): LoopSchemas.LoopScheduleTriggerConfig | null {
  // The list endpoint omits schedules; rows never render a cadence, so an
  // empty config is right there and only the detail decides the shape.
  const schedule = schedules?.[0];
  if (!schedule) return {};
  return hogFlowScheduleToScheduleConfig(schedule);
}

function loopTrigger(
  flow: LoopHogFlowSource,
  parsed: ParsedLoopActions,
): LoopSchemas.LoopTrigger | null {
  let type: LoopSchemas.LoopTriggerTypeEnum;
  let config: LoopSchemas.LoopTriggerConfig | null;
  if (parsed.trigger.type === "schedule") {
    type = "schedule";
    config = scheduleConfigFromFlow(flow.schedules);
  } else if (parsed.trigger.type === "internal-event") {
    type = "github";
    config = githubConfigFromTrigger(parsed.trigger);
  } else {
    return null;
  }
  if (!config) return null;
  return {
    id: TRIGGER_ACTION_ID,
    loop_id: flow.id,
    type,
    enabled: true,
    config,
    schedule_sync_status: null,
    last_fired_at: null,
    created_at: flow.created_at,
    updated_at: flow.updated_at,
  };
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Team skill names the loop's task step attaches; empty for a foreign flow. */
export function hogFlowTeamSkills(flow: LoopHogFlowSource): string[] {
  const parsed = parseLoopActions(flow.actions);
  const skills = parsed ? inputValue(parsed.taskInputs, "skills") : undefined;
  return Array.isArray(skills)
    ? skills.filter((skill): skill is string => typeof skill === "string")
    : [];
}

/** Whether the form can edit this flow without dropping something a person
 * built elsewhere. A save writes the whole graph, so anything the form does
 * not model would be lost. */
export function isLoopShapedHogFlow(flow: LoopHogFlowSource): boolean {
  // A staged draft is edited work the live graph does not show; a save from
  // here would land underneath it and the next publish would overwrite it.
  if (flow.draft !== undefined && flow.draft !== null) return false;
  const parsed = parseLoopActions(flow.actions);
  return (
    parsed !== null &&
    hasLoopShapedEdges(flow.edges, parsed.actions) &&
    loopTrigger(flow, parsed) !== null
  );
}

/**
 * Projects a workflow onto the loop shape the list and detail views render. A
 * flow the form did not build still maps (name, status, dates) with no
 * triggers or instructions, so the detail view can show it read-only.
 */
export function hogFlowToLoop(
  flow: LoopHogFlowSource,
  context: { projectId: number },
): LoopSchemas.Loop {
  const parsed = parseLoopActions(flow.actions);
  const trigger = parsed ? loopTrigger(flow, parsed) : null;
  const inputs = parsed?.taskInputs ?? {};
  const model = inputValue(inputs, "model");
  const repository = readString(inputValue(inputs, "repository"));
  const reasoningEffort = isRecord(model)
    ? readString(model.reasoning_effort)
    : "";
  const off = { enabled: false, events: [], params: {} };
  return {
    id: flow.id,
    team_id: context.projectId,
    created_by_id: flow.created_by?.id ?? null,
    name: flow.name ?? "",
    description: flow.description ?? "",
    visibility: "team",
    instructions: readString(inputValue(inputs, "prompt")),
    runtime_adapter: "claude",
    model: isRecord(model) ? readString(model.model) : "",
    reasoning_effort: reasoningEffort
      ? (reasoningEffort as LoopSchemas.LoopReasoningEffortEnum)
      : null,
    repositories: repository
      ? [{ github_integration_id: 0, full_name: repository }]
      : [],
    sandbox_environment_id: null,
    enabled: flow.status === "active",
    disabled_reason: null,
    overlap_policy: "skip",
    behaviors: defaultLoopBehaviors(),
    connectors: { mcp_installation_ids: [], posthog_mcp_scopes: "read_only" },
    notifications: { push: { ...off }, email: { ...off }, slack: { ...off } },
    context_target: null,
    internal: false,
    origin_product: LOOPS_ORIGIN_PRODUCT,
    last_run_at: null,
    last_run_status: null,
    last_error: null,
    consecutive_failures: 0,
    created_at: flow.created_at,
    updated_at: flow.updated_at,
    triggers: trigger ? [trigger] : [],
    skill_bundles: [],
  };
}

const TERMINAL_RUN_STATUSES: ReadonlySet<LoopSchemas.LoopRunStatusEnum> =
  new Set(["completed", "failed", "cancelled"]);

function loopRunStatus(status: unknown): LoopSchemas.LoopRunStatusEnum {
  switch (status) {
    case "started":
      return "in_progress";
    case "queued":
    case "in_progress":
    case "completed":
    case "failed":
    case "cancelled":
      return status;
    default:
      return "not_started";
  }
}

/**
 * A task the workflow created, shown as one loop run. A task with no run yet
 * still lists (as not started) so a fire that queued a task is visible before
 * the sandbox picks it up.
 */
export function taskToLoopRun(
  task: Schemas.TaskDetailDTO,
): LoopSchemas.LoopRun {
  const run = task.latest_run ?? null;
  const status = loopRunStatus(run?.status);
  const createdAt = run?.created_at ?? task.created_at ?? "";
  return {
    id: run?.id ?? task.id,
    task_id: task.id,
    loop_trigger_id: null,
    status,
    environment: run?.environment === "local" ? "local" : "cloud",
    branch: run?.branch ?? null,
    error_message: run?.error_message ?? null,
    output: run?.output ?? null,
    created_at: createdAt,
    completed_at:
      run && TERMINAL_RUN_STATUSES.has(status)
        ? (run.completed_at ?? run.updated_at ?? null)
        : null,
  };
}
