import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { flattenSelectOptions } from "@posthog/ui/features/sessions/sessionStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useState } from "react";

export interface PendingModelSwitch {
  configId: string;
  value: string;
  label: string;
  fromValue: string;
  fromLabel: string;
}

interface UsePendingModelSwitchInput {
  /** The session the queued switch belongs to. The view can swap sessions
   *  without remounting, so a queued switch clears when this changes. */
  taskId: string | undefined;
  sessionModelOption: SessionConfigOption | undefined;
  /**
   * The dialog only guards mid-session, once a prompt has been sent. Protocol
   * updates (available commands, config options) land in the event stream
   * before any prompt, so this must track conversation content, not raw events.
   */
  hasConversationStarted: boolean;
  contextTokens?: number;
  /** Applies the queued switch unchanged once the dialog is confirmed. */
  onApply: (configId: string, value: string) => Promise<boolean>;
}

interface UsePendingModelSwitchResult {
  pendingModelSwitch: PendingModelSwitch | null;
  /**
   * Queues a mid-session model switch behind the cache-cost dialog. True when
   * the change was intercepted, so the caller must not apply it itself.
   */
  interceptModelSwitch: (configId: string, value: string) => boolean;
  confirmModelSwitch: () => Promise<boolean>;
  cancelModelSwitch: () => void;
}

/**
 * A mid-session model switch first pauses on an inform-only cache-cost
 * dialog (ModelSwitchCacheDialog); confirming applies the queued switch
 * unchanged.
 */
export function usePendingModelSwitch({
  taskId,
  sessionModelOption,
  hasConversationStarted,
  contextTokens,
  onApply,
}: UsePendingModelSwitchInput): UsePendingModelSwitchResult {
  const warnOnMidSessionModelSwitch = useSettingsStore(
    (state) => state.warnOnMidSessionModelSwitch,
  );
  const [pendingModelSwitch, setPendingModelSwitch] =
    useState<PendingModelSwitch | null>(null);

  // A switch queued for one session must not linger over another. Navigating
  // to a different task does not remount this view, so drop the pending switch
  // when the task changes; otherwise confirming would write the old session's
  // choice to the new one and the dialog would show the wrong labels.
  const [trackedTaskId, setTrackedTaskId] = useState(taskId);
  if (taskId !== trackedTaskId) {
    setTrackedTaskId(taskId);
    setPendingModelSwitch(null);
  }

  const interceptModelSwitch = useCallback(
    (configId: string, value: string) => {
      const isMidSessionModelSwitch =
        warnOnMidSessionModelSwitch &&
        hasConversationStarted &&
        sessionModelOption?.type === "select" &&
        sessionModelOption.id === configId &&
        sessionModelOption.currentValue !== value;
      if (!isMidSessionModelSwitch) return false;
      const modelOptions = flattenSelectOptions(sessionModelOption.options);
      const nameOf = (modelValue: string) =>
        modelOptions.find((option) => option.value === modelValue)?.name ??
        modelValue;
      const nextSwitch = {
        configId,
        value,
        label: nameOf(value),
        fromValue: sessionModelOption.currentValue,
        fromLabel: nameOf(sessionModelOption.currentValue),
      };
      setPendingModelSwitch(nextSwitch);
      track(ANALYTICS_EVENTS.MODEL_SWITCH_WARNING_SHOWN, {
        task_id: taskId,
        from_model: nextSwitch.fromValue,
        to_model: nextSwitch.value,
        context_tokens: contextTokens,
      });
      return true;
    },
    [
      warnOnMidSessionModelSwitch,
      hasConversationStarted,
      sessionModelOption,
      taskId,
      contextTokens,
    ],
  );

  const confirmModelSwitch = useCallback(async () => {
    if (!pendingModelSwitch) return false;
    const succeeded = await onApply(
      pendingModelSwitch.configId,
      pendingModelSwitch.value,
    );
    track(ANALYTICS_EVENTS.MODEL_SWITCH_WARNING_ACTION, {
      task_id: taskId,
      from_model: pendingModelSwitch.fromValue,
      to_model: pendingModelSwitch.value,
      context_tokens: contextTokens,
      action: "switch_now",
      result: succeeded ? "succeeded" : "failed",
    });
    if (succeeded) setPendingModelSwitch(null);
    return succeeded;
  }, [pendingModelSwitch, onApply, taskId, contextTokens]);

  const cancelModelSwitch = useCallback(() => {
    if (pendingModelSwitch) {
      track(ANALYTICS_EVENTS.MODEL_SWITCH_WARNING_ACTION, {
        task_id: taskId,
        from_model: pendingModelSwitch.fromValue,
        to_model: pendingModelSwitch.value,
        context_tokens: contextTokens,
        action: "cancel",
      });
    }
    setPendingModelSwitch(null);
  }, [pendingModelSwitch, taskId, contextTokens]);

  return {
    pendingModelSwitch,
    interceptModelSwitch,
    confirmModelSwitch,
    cancelModelSwitch,
  };
}
