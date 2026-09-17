import type { LoopSchemas } from "@posthog/api-client/loops";
import { systemTimezone } from "@posthog/ui/primitives/timezone";

/**
 * A trigger row in the create/edit form. `key` is a client-only stable
 * identity for list rendering (new rows have no server `id` yet); `id` is
 * only present once the trigger has been persisted, and is carried through
 * to the write payload so the backend updates the row in place instead of
 * creating a duplicate (see the Lifecycle section of the Loops spec on
 * id-stable trigger writes).
 */
/** The trigger kinds a loop's workflow can carry. */
export type LoopTriggerType = "schedule" | "github";

export interface LoopTriggerDraft {
  key: string;
  id?: string;
  type: LoopSchemas.LoopTriggerTypeEnum;
  enabled: boolean;
  config: LoopSchemas.LoopTriggerConfig;
}

/** The context a loop is attached to in the form. `null` on `LoopFormValues.contextTarget`
 * means the loop isn't attached to any context. */
export interface LoopContextTargetDraft {
  folderId: string;
  name: string;
  outputs: LoopSchemas.LoopContextOutputs;
}

export interface LoopFormValues {
  name: string;
  description: string;
  visibility: LoopSchemas.LoopVisibilityEnum;
  instructions: string;
  runtimeAdapter: LoopSchemas.LoopRuntimeAdapterEnum;
  model: string;
  reasoningEffort: LoopSchemas.LoopReasoningEffortEnum | null;
  /**
   * Full desired repository list. The form's picker only edits the first
   * entry; any additional entries are carried through untouched so saving an
   * unrelated change never drops a loop's other repository associations.
   */
  repositories: LoopSchemas.LoopRepositoryEntry[];
  sandboxEnvironmentId: string | null;
  triggers: LoopTriggerDraft[];
  behaviors: LoopSchemas.LoopBehaviors;
  notifications: LoopSchemas.LoopNotifications;
  contextTarget: LoopContextTargetDraft | null;
  /** Names of team skills the loop's task step attaches. */
  teamSkills: string[];
}

function emptyLoopScheduleTriggerConfig(): LoopSchemas.LoopScheduleTriggerConfig {
  return { cron_expression: "0 9 * * 1", timezone: systemTimezone() };
}

function emptyLoopGithubTriggerConfig(): LoopSchemas.LoopGithubTriggerConfig {
  return { github_integration_id: 0, repository: "", events: [] };
}

/** The `action` values GitHub sends for each webhook event we subscribe to. Push carries no
 * action at all. */
const GITHUB_EVENT_ACTIONS: Record<
  LoopSchemas.LoopGithubTriggerEventEnum,
  string[]
> = {
  push: [],
  pull_request: [
    "opened",
    "reopened",
    "closed",
    "synchronize",
    "edited",
    "ready_for_review",
    "converted_to_draft",
    "review_requested",
    "review_request_removed",
    "labeled",
    "unlabeled",
    "assigned",
    "unassigned",
  ],
  issues: [
    "opened",
    "reopened",
    "closed",
    "edited",
    "deleted",
    "labeled",
    "unlabeled",
    "assigned",
    "unassigned",
    "pinned",
    "unpinned",
    "transferred",
  ],
  issue_comment: ["created", "edited", "deleted"],
};

/** Actions offerable for a set of events, which is their intersection rather than their union:
 * one `filters.actions` list is matched against every event on the trigger, so an action only
 * some of them can send would stop the others firing entirely. */
export function githubTriggerActionOptions(
  events: LoopSchemas.LoopGithubTriggerEventEnum[],
): string[] {
  if (events.length === 0) {
    return [];
  }
  return events
    .map((event) => GITHUB_EVENT_ACTIONS[event] ?? [])
    .reduce((shared, actions) =>
      shared.filter((action) => actions.includes(action)),
    );
}

/** Every action GITHUB_EVENT_ACTIONS models. GitHub keeps adding actions, and the API accepts any
 * string, so a trigger can hold one we don't list — we can't tell which events send it. */
const MODELLED_GITHUB_ACTIONS = new Set(
  Object.values(GITHUB_EVENT_ACTIONS).flat(),
);

/** Sets the trigger's events, dropping any selected action the new set can't all send. Leaving
 * a stale action behind would silently stop the newly ticked event from ever firing.
 *
 * Actions we don't model are kept: dropping one would widen the trigger to every action of the
 * event, and since the user was never shown a control for it they'd get no say in that. */
export function withGithubTriggerEvents(
  config: LoopSchemas.LoopGithubTriggerConfig,
  events: LoopSchemas.LoopGithubTriggerEventEnum[],
): LoopSchemas.LoopGithubTriggerConfig {
  const offerable = githubTriggerActionOptions(events);
  const actions = (config.filters?.actions ?? []).filter(
    (action) =>
      offerable.includes(action) || !MODELLED_GITHUB_ACTIONS.has(action),
  );
  return withGithubTriggerFilters({ ...config, events }, { actions });
}

/** Applies a filter patch, dropping keys that end up empty so an untouched trigger doesn't
 * grow `{actions: [], payload: []}` noise in its stored config. */
export function withGithubTriggerFilters(
  config: LoopSchemas.LoopGithubTriggerConfig,
  patch: Partial<LoopSchemas.LoopGithubTriggerFilters>,
): LoopSchemas.LoopGithubTriggerConfig {
  const merged = { ...config.filters, ...patch };
  const filters = Object.fromEntries(
    Object.entries(merged).filter(
      ([, value]) => !Array.isArray(value) || value.length > 0,
    ),
  ) as LoopSchemas.LoopGithubTriggerFilters;
  return { ...config, filters };
}

function defaultLoopNotifications(): LoopSchemas.LoopNotifications {
  const off = { enabled: false, events: [], params: {} };
  return { push: { ...off }, email: { ...off }, slack: { ...off } };
}

export function defaultLoopBehaviors(): LoopSchemas.LoopBehaviors {
  return {
    create_prs: true,
    watch_ci: false,
    fix_review_comments: false,
    max_fix_iterations: 3,
  };
}

/** Sensible defaults when a loop is first attached to a context: file its runs into the
 * feed, but don't touch context.md or a canvas until the user opts in. */
export function defaultLoopContextOutputs(): LoopSchemas.LoopContextOutputs {
  return { post_to_feed: true, update_context: false, canvas_id: null };
}

/** The single "Auto-fix pull requests" toggle drives both CI-watching and
 * review-comment fixing; it reads as on only when both are on. */
export function isAutoFixEnabled(
  behaviors: LoopSchemas.LoopBehaviors,
): boolean {
  return behaviors.watch_ci && behaviors.fix_review_comments;
}

let draftKeySeq = 0;

export function nextDraftTriggerKey(): string {
  draftKeySeq += 1;
  return `draft-trigger-${draftKeySeq}`;
}

function defaultLoopScheduleTrigger(): LoopTriggerDraft {
  return {
    key: nextDraftTriggerKey(),
    type: "schedule",
    enabled: true,
    config: emptyLoopScheduleTriggerConfig(),
  };
}

export function defaultLoopTriggerOfType(
  type: LoopTriggerType,
): LoopTriggerDraft {
  if (type === "schedule") return defaultLoopScheduleTrigger();
  return {
    key: nextDraftTriggerKey(),
    type,
    enabled: true,
    config: emptyLoopGithubTriggerConfig(),
  };
}

export function emptyLoopFormValues(): LoopFormValues {
  return {
    name: "",
    description: "",
    visibility: "personal",
    instructions: "",
    runtimeAdapter: "claude",
    model: "",
    reasoningEffort: null,
    repositories: [],
    sandboxEnvironmentId: null,
    triggers: [defaultLoopScheduleTrigger()],
    behaviors: defaultLoopBehaviors(),
    notifications: defaultLoopNotifications(),
    contextTarget: null,
    teamSkills: [],
  };
}

/** A context-attached loop files its runs into the context's shared feed, so it must be
 * team-visible. The backend rejects personal + context; this keeps form state consistent
 * for prefills (e.g. "New loop" from a context page) and legacy loops. */
export function normalizeLoopFormValues(
  values: LoopFormValues,
): LoopFormValues {
  if (values.contextTarget && values.visibility !== "team") {
    return { ...values, visibility: "team" };
  }
  return values;
}

export function loopToFormValues(loop: LoopSchemas.Loop): LoopFormValues {
  return {
    name: loop.name,
    description: loop.description,
    visibility: loop.visibility,
    instructions: loop.instructions,
    runtimeAdapter: loop.runtime_adapter,
    model: loop.model,
    reasoningEffort: loop.reasoning_effort,
    repositories: [...loop.repositories],
    sandboxEnvironmentId: loop.sandbox_environment_id,
    triggers: loop.triggers.map((trigger) => ({
      key: trigger.id,
      id: trigger.id,
      type: trigger.type,
      enabled: trigger.enabled,
      config: trigger.config,
    })),
    behaviors: loop.behaviors,
    notifications: loop.notifications,
    contextTarget: loop.context_target
      ? {
          folderId: loop.context_target.folder_id,
          name: loop.context_target.name,
          outputs: loop.context_target.outputs,
        }
      : null,
    teamSkills: [],
  };
}

export function isLoopFormValid(values: LoopFormValues): boolean {
  if (!values.name.trim()) {
    return false;
  }
  if (!values.instructions.trim()) {
    return false;
  }
  if (values.contextTarget && values.visibility !== "team") {
    return false;
  }
  return isTriggerListValid(values.triggers);
}

/** A workflow holds exactly one enabled trigger. */
export function isTriggerListValid(triggers: LoopTriggerDraft[]): boolean {
  const [trigger, ...rest] = triggers;
  if (!trigger || rest.length > 0 || !trigger.enabled) {
    return false;
  }
  return isTriggerDraftValid(trigger);
}

/** A workflow resolves the GitHub repository itself, so no integration id is
 * needed, and it listens to one event type. */
export function isTriggerDraftValid(trigger: LoopTriggerDraft): boolean {
  if (trigger.type === "schedule") {
    const config = trigger.config as LoopSchemas.LoopScheduleTriggerConfig;
    return !!config.run_at || !!config.cron_expression;
  }
  if (trigger.type === "github") {
    const config = trigger.config as LoopSchemas.LoopGithubTriggerConfig;
    return (
      !!config.repository &&
      config.events.length === 1 &&
      (config.filters?.payload ?? []).every(isPayloadConditionValid)
    );
  }
  return false;
}

/** Each accepted value is its own chip in the editor, never a delimited string. An earlier
 * version split this field on commas, which both lost a value that legitimately contains one
 * (`pull_request.title` is a matchable path) and quietly widened the gate: an exact condition
 * of "release, approved" became two alternatives, so a PR titled just "approved" matched. */
function payloadConditionValues(
  condition: LoopSchemas.LoopGithubTriggerPayloadFilter,
): string[] {
  const values = Array.isArray(condition.equals)
    ? condition.equals
    : [condition.equals];
  return values.map((value) => value.trim()).filter(Boolean);
}

// A half-filled row would submit and come back as a 400 from the trigger serializer.
function isPayloadConditionValid(
  condition: LoopSchemas.LoopGithubTriggerPayloadFilter,
): boolean {
  return (
    !!condition.path.trim() && payloadConditionValues(condition).length > 0
  );
}
