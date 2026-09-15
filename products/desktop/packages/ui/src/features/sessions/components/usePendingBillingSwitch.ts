import type { Adapter, ModelAccess } from "@posthog/shared";
import { useCallback, useState } from "react";

export interface PendingBillingSwitch {
  adapter: Adapter;
  access: ModelAccess;
  queuedCount: number;
}

interface UsePendingBillingSwitchInput {
  /** The session the queued switch belongs to. The view can swap sessions
   *  without remounting, so a queued switch clears when this changes. */
  taskId: string | undefined;
  /** Number of messages queued behind the running turn. */
  queuedCount: number;
  /** The run's current billing for the adapter being switched. */
  currentAccess: ModelAccess | undefined;
  /** Applies the switch once the dialog is confirmed. */
  onApply: (adapter: Adapter, access: ModelAccess) => void;
}

interface UsePendingBillingSwitchResult {
  pendingBillingSwitch: PendingBillingSwitch | null;
  /**
   * Holds a billing switch behind the discard-queue dialog when the switch
   * would drop queued messages. True when the change was intercepted, so the
   * caller must not apply it itself.
   */
  interceptBillingSwitch: (adapter: Adapter, access: ModelAccess) => boolean;
  confirmBillingSwitch: () => void;
  cancelBillingSwitch: () => void;
}

/**
 * Switching a running conversation's billing respawns the agent on the next
 * message, which resends the conversation and drops the queue. When messages
 * are queued, pause on a confirm dialog first (BillingSwitchQueuedDialog);
 * confirming applies the switch, which clears the queue.
 */
export function usePendingBillingSwitch({
  taskId,
  queuedCount,
  currentAccess,
  onApply,
}: UsePendingBillingSwitchInput): UsePendingBillingSwitchResult {
  const [pendingBillingSwitch, setPendingBillingSwitch] =
    useState<PendingBillingSwitch | null>(null);

  // A switch queued for one session must not linger over another. Navigating to
  // a different task does not remount this view, so drop the pending switch when
  // the task changes.
  const [trackedTaskId, setTrackedTaskId] = useState(taskId);
  if (taskId !== trackedTaskId) {
    setTrackedTaskId(taskId);
    setPendingBillingSwitch(null);
  }

  const interceptBillingSwitch = useCallback(
    (adapter: Adapter, access: ModelAccess) => {
      const wouldDropQueue = access !== currentAccess && queuedCount > 0;
      if (!wouldDropQueue) return false;
      setPendingBillingSwitch({ adapter, access, queuedCount });
      return true;
    },
    [currentAccess, queuedCount],
  );

  const confirmBillingSwitch = useCallback(() => {
    if (!pendingBillingSwitch) return;
    onApply(pendingBillingSwitch.adapter, pendingBillingSwitch.access);
    setPendingBillingSwitch(null);
  }, [pendingBillingSwitch, onApply]);

  const cancelBillingSwitch = useCallback(() => {
    setPendingBillingSwitch(null);
  }, []);

  return {
    pendingBillingSwitch,
    interceptBillingSwitch,
    confirmBillingSwitch,
    cancelBillingSwitch,
  };
}
