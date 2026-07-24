import type {
  ContentBlock,
  RequestPermissionRequest,
  SessionConfigOption,
  SessionConfigSelectGroup,
  SessionConfigSelectOption,
  SessionConfigSelectOptions,
} from "@agentclientprotocol/sdk";
import type { Adapter } from "./adapter";
import type { SkillButtonId } from "./analytics-events";
import type { ExecutionMode } from "./exec-types";
import type { AcpMessage } from "./session-events";
import type { TaskRunArtifact, TaskRunStatus } from "./task";

export type { Adapter };

export type PermissionRequest = Omit<RequestPermissionRequest, "sessionId"> & {
  taskRunId: string;
  receivedAt: number;
};

export interface QueuedMessage {
  id: string;
  content: string;
  rawPrompt?: string | ContentBlock[];
  queuedAt: number;
}

export type OptimisticItem =
  | {
      type: "user_message";
      id: string;
      content: string;
      timestamp: number;
      pinToTop?: boolean;
    }
  | {
      type: "skill_button_action";
      id: string;
      buttonId: SkillButtonId;
    };

export type SessionStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

export interface AgentSession {
  taskRunId: string;
  taskId: string;
  taskTitle: string;
  channel: string;
  events: AcpMessage[];
  startedAt: number;
  status: SessionStatus;
  errorTitle?: string;
  errorMessage?: string;
  errorRetryable?: boolean;
  isPromptPending: boolean;
  isCompacting: boolean;
  promptStartedAt: number | null;
  currentPromptId?: number | null;
  logUrl?: string;
  /** Full cloud transcript entry count across the resume chain. */
  cloudTranscriptEntryCount?: number;
  /** Leaf-run cursor used to reconcile live cloud log updates. */
  processedLineCount?: number;
  framework?: "claude";
  adapter?: Adapter;
  model?: string;
  executionMode?: ExecutionMode;
  reasoningLevel?: string;
  configOptions?: SessionConfigOption[];
  /**
   * Adapter's negotiated steering capability (`_meta.posthog.steering` from
   * initialize). "native" means a mid-turn message folds into the running turn
   * (claude, codex); "interrupt-resend" (legacy) or undefined
   * means the host must cancel + resend. Drives the steer-vs-resend decision.
   */
  steering?: string;
  pendingPermissions: Map<string, PermissionRequest>;
  pausedDurationMs: number;
  messageQueue: QueuedMessage[];
  /**
   * Id of the queued message the user currently has open in the composer for an
   * in-place edit, if any. While set it acts as a drain boundary: when the turn
   * ends, everything queued *before* this message auto-sends, but this message
   * and everything after it stay queued until the edit is saved or cancelled.
   * See {@link sendableQueuePrefixLength}.
   */
  editingQueuedId?: string;
  isCloud?: boolean;
  cloudStatus?: TaskRunStatus;
  cloudStage?: string | null;
  cloudOutput?: Record<string, unknown> | null;
  cloudArtifacts?: TaskRunArtifact[];
  cloudErrorMessage?: string | null;
  initialPrompt?: ContentBlock[];
  cloudBranch?: string | null;
  handoffInProgress?: boolean;
  stopRequested?: boolean;
  optimisticItems: OptimisticItem[];
  contextUsed?: number;
  contextSize?: number;
  conversationSummary?: string;
  idleKilled?: boolean;
  agentVersion?: string;
  agentIdleForRunId?: string;
}

/**
 * How many messages at the head of the queue are eligible to auto-send when the
 * turn ends. A message being edited in place ({@link AgentSession.editingQueuedId})
 * is a hard boundary: the messages queued before it may send, but it and
 * everything after it stay put until the edit is saved or cancelled. Returns the
 * full queue length when nothing is being edited, or when the edited message has
 * already left the queue (e.g. it was discarded).
 */
export function sendableQueuePrefixLength(
  session: Pick<AgentSession, "messageQueue" | "editingQueuedId">,
): number {
  const { messageQueue, editingQueuedId } = session;
  if (!editingQueuedId) return messageQueue.length;
  const editIndex = messageQueue.findIndex((m) => m.id === editingQueuedId);
  return editIndex === -1 ? messageQueue.length : editIndex;
}

export function isSelectGroup(
  options: SessionConfigSelectOptions,
): options is SessionConfigSelectGroup[] {
  return (
    options.length > 0 &&
    typeof options[0] === "object" &&
    "options" in options[0]
  );
}

export function flattenSelectOptions(
  options: SessionConfigSelectOptions,
): SessionConfigSelectOption[] {
  if (!options.length) return [];
  if (isSelectGroup(options)) {
    return options.flatMap((group) => group.options);
  }
  return options as SessionConfigSelectOption[];
}

export function mergeConfigOptions(
  live: SessionConfigOption[],
  persisted: SessionConfigOption[],
): SessionConfigOption[] {
  const persistedMap = new Map(persisted.map((opt) => [opt.id, opt]));

  return live.map((liveOpt) => {
    const persistedOpt = persistedMap.get(liveOpt.id);
    if (persistedOpt) {
      return {
        ...liveOpt,
        currentValue: persistedOpt.currentValue,
      } as SessionConfigOption;
    }
    return liveOpt;
  });
}

/**
 * Whether a persisted config option can be restored into a resumed session's
 * live options. The live session must still advertise an option with the same
 * id and type, and — for selects — must still offer the persisted value.
 * Matching by id alone would restore a value the resumed agent dropped (e.g. a
 * reasoning level the resumed model no longer supports), which the server
 * rejects and which leaves the UI showing a setting that never took effect.
 */
export function isPersistedOptionSupported(
  persisted: SessionConfigOption,
  liveOptions: SessionConfigOption[],
): boolean {
  const live = liveOptions.find((opt) => opt.id === persisted.id);
  if (!live || live.type !== persisted.type) return false;
  if (live.type === "select") {
    return flattenSelectOptions(live.options).some(
      (opt) => opt.value === persisted.currentValue,
    );
  }
  return true;
}

export function getConfigOptionByCategory(
  configOptions: SessionConfigOption[] | undefined,
  category: string,
): SessionConfigOption | undefined {
  return configOptions?.find((opt) => opt.category === category);
}

export function cycleModeOption(
  modeOption: SessionConfigOption | undefined,
  options?: { allowBypassPermissions?: boolean },
): string | undefined {
  if (!modeOption || modeOption.type !== "select") return undefined;

  const allOptions = flattenSelectOptions(modeOption.options);
  const filtered = options?.allowBypassPermissions
    ? allOptions
    : allOptions.filter(
        (opt) =>
          opt.value !== "bypassPermissions" && opt.value !== "full-access",
      );
  if (filtered.length === 0) return undefined;

  const currentIndex = filtered.findIndex(
    (opt) => opt.value === modeOption.currentValue,
  );
  if (currentIndex === -1) return filtered[0]?.value;

  const nextIndex = (currentIndex + 1) % filtered.length;
  return filtered[nextIndex]?.value;
}

export function getCurrentModeFromConfigOptions(
  configOptions: SessionConfigOption[] | undefined,
): ExecutionMode | undefined {
  const modeOption = getConfigOptionByCategory(configOptions, "mode");
  return modeOption?.currentValue as ExecutionMode | undefined;
}

/**
 * The safe non-bypass mode to revert to when "Bypass permissions" is turned
 * off, chosen from the session's OWN mode options so it's always valid for that
 * adapter. Claude exposes "default"; codex has no "default" (its presets are
 * plan/read-only/auto/full-access) so it falls back to "auto" — reverting codex
 * to "default" would set an unknown mode (no approvalPolicy → an undefined
 * approval state). Returns undefined when there is no usable mode option.
 */
export function resolveBypassRevertMode(
  modeOption: SessionConfigOption | undefined,
): string | undefined {
  if (modeOption?.type !== "select") return undefined;
  const opts = flattenSelectOptions(modeOption.options);
  const isBypass = (v: string) =>
    v === "bypassPermissions" || v === "full-access";
  if (opts.some((o) => o.value === "default")) return "default";
  if (opts.some((o) => o.value === "auto")) return "auto";
  return opts.find((o) => !isBypass(o.value))?.value;
}

/**
 * Whether a mid-turn message can be folded into the running turn (steered)
 * rather than interrupt-and-resent. Decided by the adapter's negotiated
 * `steering` capability: "native" folds (claude, codex app-server);
 * "interrupt-resend" (legacy) does not.
 *
 * Fallback: if `steering` is unset (a start path that predates capability
 * plumbing), Claude is still treated as native — it has always steered — so the
 * capability rollout can never regress it.
 */
export function sessionSupportsNativeSteer(
  session: Pick<AgentSession, "isCloud" | "steering" | "adapter">,
): boolean {
  if (session.steering === "native") return true;
  if (session.isCloud) return false;
  return session.steering == null && session.adapter === "claude";
}
