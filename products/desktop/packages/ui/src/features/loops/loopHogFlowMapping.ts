import type { LoopSchemas } from "@posthog/api-client/loops";
import {
  CREATE_TASK_ACTION_ID,
  CREATE_TASK_NON_FAILURE_STATUS_CODES,
  CREATE_TASK_TEMPLATE_ID,
  findCreateTaskAction,
  isLoopShapedHogFlow,
  TRIGGER_ACTION_ID,
  type WorkflowSchemas,
} from "@posthog/api-client/workflows";
import type { Task } from "@posthog/shared/domain-types";
import {
  type LoopFormValues,
  type LoopTriggerDraft,
  nextDraftTriggerKey,
} from "./loopFormTypes";
import {
  loopScheduleTriggerConfigToRRuleWrite,
  rruleScheduleToLoopTriggerConfig,
} from "./loopScheduleRRule";

/**
 * Maps the loop form onto a HogFlow instead of a Loop, for the hog_flows-backed variant of the
 * feature (see `useLoops` and friends). Only the fields the create-task action and schedule
 * trigger actually support round-trip; everything the plan cut for v1 (notifications, context
 * attachment, sandbox environment, connectors, GitHub/API triggers, overlap policy) has no
 * counterpart here.
 */

function buildTriggerAction(): WorkflowSchemas.TriggerAction {
  return {
    id: TRIGGER_ACTION_ID,
    name: "Schedule",
    type: "trigger",
    config: { type: "schedule" },
  };
}

function buildCreateTaskAction(
  values: LoopFormValues,
): WorkflowSchemas.CreateTaskAction {
  const inputs: WorkflowSchemas.CreateTaskActionInputs = {
    prompt: { value: values.instructions.trim() },
    non_failure_status_codes: { value: CREATE_TASK_NON_FAILURE_STATUS_CODES },
  };
  if (values.model.trim()) {
    inputs.model = {
      value: {
        model: values.model.trim(),
        reasoning_effort: values.reasoningEffort ?? undefined,
      },
    };
  }
  if (values.repositories[0]?.full_name) {
    inputs.repository = { value: values.repositories[0].full_name };
  }
  if (values.skillNames.length > 0) {
    inputs.skills = { value: values.skillNames };
  }
  return {
    id: CREATE_TASK_ACTION_ID,
    name: "Create AI task",
    type: "function",
    config: { template_id: CREATE_TASK_TEMPLATE_ID, inputs },
    output_variable: { key: "task", result_path: null, label: "Task" },
  };
}

/** Builds the `actions`/`edges` this feature writes for a loop-shaped HogFlow. `status` is
 * separate because it toggles independently of everything else (the loop's own "enabled"
 * switch), and callers already track it against the flow they're patching. */
export function formValuesToHogFlowWrite(
  values: LoopFormValues,
  status: WorkflowSchemas.HogFlowStatus,
): WorkflowSchemas.HogFlowWrite {
  return {
    name: values.name.trim(),
    description: values.description.trim(),
    status,
    actions: [buildTriggerAction(), buildCreateTaskAction(values)],
    edges: [
      { from: TRIGGER_ACTION_ID, to: CREATE_TASK_ACTION_ID, type: "continue" },
    ],
  };
}

/** The schedule sub-resource write for the form's (single) schedule trigger, or null when the
 * trigger's cron isn't one the picker itself would have written — see
 * `loopScheduleTriggerConfigToRRuleWrite`. Callers should block save on a null result rather
 * than silently drop the timing. */
export function formValuesToScheduleWrite(
  values: LoopFormValues,
): WorkflowSchemas.HogFlowScheduleWrite | null {
  const trigger = values.triggers[0];
  if (!trigger) return null;
  return loopScheduleTriggerConfigToRRuleWrite(
    trigger.config as {
      cron_expression?: string;
      timezone?: string;
      run_at?: string;
    },
  );
}

export function emptyHogFlowLoopFormValues(): LoopFormValues {
  return {
    name: "",
    description: "",
    visibility: "team",
    instructions: "",
    skill: null,
    skillContext: "",
    skillNames: [],
    runtimeAdapter: "claude",
    model: "",
    reasoningEffort: null,
    repositories: [],
    sandboxEnvironmentId: null,
    triggers: [
      {
        key: nextDraftTriggerKey(),
        type: "schedule",
        enabled: true,
        config: { cron_expression: "0 9 * * 1", timezone: "UTC" },
      },
    ],
    behaviors: HOG_FLOW_LOOP_BEHAVIORS,
    notifications: emptyLoopNotifications(),
    contextTarget: null,
  };
}

const HOG_FLOW_LOOP_BEHAVIORS: LoopSchemas.LoopBehaviors = {
  create_prs: true,
  watch_ci: false,
  fix_review_comments: false,
  max_fix_iterations: 3,
};

function emptyLoopNotifications(): LoopSchemas.LoopNotifications {
  return {
    push: { enabled: false, events: [], params: {} },
    email: { enabled: false, events: [], params: {} },
    slack: { enabled: false, events: [], params: {} },
  };
}

/** Reads the create-task action's inputs shared by every read direction (form values, list
 * row, detail view) — one action shape, three renderings. */
function deriveCreateTaskFields(actions: WorkflowSchemas.HogFlowAction[]): {
  instructions: string;
  model: string;
  reasoningEffort: LoopSchemas.LoopReasoningEffortEnum | null;
  repositories: LoopSchemas.LoopRepositoryEntry[];
  skillNames: string[];
} {
  const inputs = findCreateTaskAction(actions)?.config.inputs;
  return {
    instructions: inputs?.prompt.value ?? "",
    model: inputs?.model?.value.model ?? "",
    reasoningEffort:
      (inputs?.model?.value
        .reasoning_effort as LoopSchemas.LoopReasoningEffortEnum | null) ??
      null,
    // The create-task action's `repository` input is a plain "org/repo" string with no
    // integration id — `github_integration_id: 0` is a display-only placeholder for
    // `LoopRepositoryPicker`, never sent back on write (see `buildCreateTaskAction`).
    repositories: inputs?.repository?.value
      ? [{ github_integration_id: 0, full_name: inputs.repository.value }]
      : [],
    skillNames: inputs?.skills?.value ?? [],
  };
}

/** Decompiles a HogFlow list row onto the `Loop` shape `LoopRow`/`LoopsListView` already
 * render, so those components don't need a hog_flows-specific variant. Fields the minimal
 * list response doesn't carry (last run status, consecutive failures, disabled reason) default
 * to their "healthy, no history yet" values rather than being guessed at — the detail view
 * (`hogFlowToLoop`) is where a caller gets the real ones. */
export function hogFlowMinimalToLoop(
  flow: WorkflowSchemas.HogFlowMinimal,
): LoopSchemas.Loop {
  const fields = deriveCreateTaskFields(flow.actions);
  return {
    id: flow.id,
    team_id: 0,
    created_by_id: flow.created_by.id,
    name: flow.name ?? "",
    description: flow.description,
    visibility: "team",
    instructions: fields.instructions,
    runtime_adapter: "claude",
    model: fields.model,
    reasoning_effort: fields.reasoningEffort,
    repositories: fields.repositories,
    sandbox_environment_id: null,
    enabled: flow.status === "active",
    disabled_reason: null,
    overlap_policy: "skip",
    behaviors: HOG_FLOW_LOOP_BEHAVIORS,
    connectors: { mcp_installation_ids: [], posthog_mcp_scopes: "read_only" },
    notifications: emptyLoopNotifications(),
    context_target: null,
    internal: false,
    origin_product: "user_created",
    last_run_at: null,
    last_run_status: null,
    last_error: null,
    consecutive_failures: 0,
    created_at: flow.created_at,
    updated_at: flow.updated_at,
    // The minimal list response carries no schedule — a list row never reads triggers
    // (see `LoopRow`), so this stays empty rather than faking one.
    triggers: [],
  };
}

/** Decompiles a full HogFlow (plus its schedule) onto the `Loop` shape `LoopDetailView` already
 * renders. Unlike `hogFlowMinimalToLoop`, this carries a real trigger — the detail view reads
 * it for its read-only "configuration summary" section. */
export function hogFlowToLoop(
  flow: WorkflowSchemas.HogFlow,
  schedule: WorkflowSchemas.HogFlowSchedule | null,
): LoopSchemas.Loop {
  const fields = deriveCreateTaskFields(flow.actions);
  const scheduleConfig = schedule
    ? rruleScheduleToLoopTriggerConfig(schedule)
    : null;

  return {
    id: flow.id,
    team_id: 0,
    created_by_id: flow.created_by.id,
    name: flow.name ?? "",
    description: flow.description,
    visibility: "team",
    instructions: fields.instructions,
    runtime_adapter: "claude",
    model: fields.model,
    reasoning_effort: fields.reasoningEffort,
    repositories: fields.repositories,
    sandbox_environment_id: null,
    enabled: flow.status === "active",
    disabled_reason: null,
    overlap_policy: "skip",
    behaviors: HOG_FLOW_LOOP_BEHAVIORS,
    connectors: { mcp_installation_ids: [], posthog_mcp_scopes: "read_only" },
    notifications: emptyLoopNotifications(),
    context_target: null,
    internal: false,
    origin_product: "user_created",
    last_run_at: null,
    last_run_status: null,
    last_error: null,
    consecutive_failures: 0,
    created_at: flow.created_at,
    updated_at: flow.updated_at,
    triggers: [
      {
        id: TRIGGER_ACTION_ID,
        loop_id: flow.id,
        type: "schedule",
        enabled: flow.status === "active",
        config: scheduleConfig ?? {},
        schedule_sync_status: null,
        last_fired_at: null,
        created_at: flow.created_at,
        updated_at: flow.updated_at,
      },
    ],
  };
}

/** True once every part of the flow this feature didn't explicitly write has been checked:
 * the action/edge shape (see `isLoopShapedHogFlow`) and, separately, whether its schedule's
 * RRULE is one the form's picker would have produced. A flow failing either check was built or
 * edited outside this feature and should render read-only — see `LoopDetailView`. */
export function isDecompilableLoopHogFlow(
  flow: Pick<WorkflowSchemas.HogFlow, "actions" | "edges">,
  schedule: Pick<
    WorkflowSchemas.HogFlowSchedule,
    "rrule" | "starts_at" | "timezone"
  > | null,
): boolean {
  if (!isLoopShapedHogFlow(flow)) return false;
  if (!schedule) return false;
  return rruleScheduleToLoopTriggerConfig(schedule) !== null;
}

export function hogFlowToFormValues(
  flow: WorkflowSchemas.HogFlow,
  schedule: WorkflowSchemas.HogFlowSchedule | null,
): LoopFormValues {
  const fields = deriveCreateTaskFields(flow.actions);
  const scheduleConfig = schedule
    ? rruleScheduleToLoopTriggerConfig(schedule)
    : null;

  const trigger: LoopTriggerDraft = {
    key: TRIGGER_ACTION_ID,
    id: TRIGGER_ACTION_ID,
    type: "schedule",
    enabled: flow.status === "active",
    config: scheduleConfig ?? {},
  };

  return {
    name: flow.name ?? "",
    description: flow.description,
    visibility: "team",
    instructions: fields.instructions,
    skill: null,
    skillContext: "",
    skillNames: fields.skillNames,
    runtimeAdapter: "claude",
    model: fields.model,
    reasoningEffort: fields.reasoningEffort,
    repositories: fields.repositories,
    sandboxEnvironmentId: null,
    triggers: [trigger],
    behaviors: HOG_FLOW_LOOP_BEHAVIORS,
    notifications: emptyLoopNotifications(),
    contextTarget: null,
  };
}

export function isHogFlowLoopFormValid(values: LoopFormValues): boolean {
  if (!values.name.trim()) return false;
  if (!values.instructions.trim()) return false;
  const trigger = values.triggers[0];
  if (!trigger) return false;
  return formValuesToScheduleWrite(values) !== null;
}

/** Adapts a generic task's latest run onto the `LoopRun` shape `LoopRunRow` already renders,
 * so that component doesn't need a hog_flows-specific variant. `TaskRunStatus`/
 * `TaskRunEnvironment` share their values with `LoopRunStatusEnum`/`LoopRunEnvironmentEnum`
 * exactly, so this is a field rename, not a translation. Returns null for a task with no run
 * yet (shouldn't happen for a workflow-spawned task, but the type allows it). */
export function taskToLoopRun(task: Task): LoopSchemas.LoopRun | null {
  const run = task.latest_run;
  if (!run) return null;
  return {
    id: run.id,
    task_id: task.id,
    loop_trigger_id: null,
    status: run.status,
    environment: run.environment ?? "cloud",
    branch: run.branch,
    error_message: run.error_message,
    output: run.output,
    created_at: run.created_at,
    completed_at: run.completed_at,
  };
}
