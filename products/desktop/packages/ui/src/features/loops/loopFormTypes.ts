import type { LoopSchemas } from "@posthog/ui/features/loops/loopSchemas";
import { systemTimezone } from "@posthog/ui/primitives/timezone";

/** A trigger row in the create/edit form. `key` is a client-only stable
 * identity for list rendering. */
export interface LoopTriggerDraft {
  key: string;
  type: LoopSchemas.LoopTriggerTypeEnum;
  enabled: boolean;
  config: LoopSchemas.LoopTriggerConfig;
}

/** The context a loop is attached to in the form. `null` on `LoopFormValues.contextTarget`
 * means the loop isn't attached to any context. */
export interface LoopContextTargetDraft {
  folderId: string;
  name: string;
}

export interface LoopFormValues {
  name: string;
  description: string;
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
  triggers: LoopTriggerDraft[];
  contextTarget: LoopContextTargetDraft | null;
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
 * grow `{actions: []}` noise in its stored config. */
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
  type: LoopSchemas.LoopTriggerTypeEnum,
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
    instructions: "",
    runtimeAdapter: "claude",
    model: "",
    reasoningEffort: null,
    repositories: [],
    triggers: [defaultLoopScheduleTrigger()],
    contextTarget: null,
    teamSkills: [],
  };
}

export function loopToFormValues(loop: LoopSchemas.Loop): LoopFormValues {
  return {
    name: loop.name,
    description: loop.description,
    instructions: loop.instructions,
    runtimeAdapter: loop.runtime_adapter,
    model: loop.model,
    reasoningEffort: loop.reasoning_effort,
    repositories: [...loop.repositories],
    triggers: loop.triggers.map((trigger) => ({
      key: trigger.id,
      type: trigger.type,
      enabled: trigger.enabled,
      config: trigger.config,
    })),
    contextTarget: loop.context_target
      ? {
          folderId: loop.context_target.channel_id,
          name: loop.context_target.name,
        }
      : null,
    teamSkills: [],
  };
}

export function isLoopFormValid(values: LoopFormValues): boolean {
  if (!values.name.trim() || !values.instructions.trim()) {
    return false;
  }
  return isTriggerListValid(values.triggers);
}

// The workflow resolves the GitHub repository itself, so no integration id is needed.
export function isTriggerListValid(triggers: LoopTriggerDraft[]): boolean {
  const [trigger, ...rest] = triggers;
  if (!trigger || rest.length > 0 || !trigger.enabled) {
    return false;
  }
  return isTriggerDraftValid(trigger);
}

export function isTriggerDraftValid(trigger: LoopTriggerDraft): boolean {
  if (trigger.type === "schedule") {
    const config = trigger.config as LoopSchemas.LoopScheduleTriggerConfig;
    return !!config.run_at || !!config.cron_expression;
  }
  const config = trigger.config as LoopSchemas.LoopGithubTriggerConfig;
  return !!config.repository && config.events.length === 1;
}
