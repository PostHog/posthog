import { router } from "expo-router";
import { useEffect } from "react";
import { useAuthStore } from "@/features/auth";
import { logger } from "@/lib/logger";
import { pendingPromptRecoveryStoreApi } from "../stores/pendingPromptRecoveryStore";

const log = logger.scope("pending-prompt-recovery");

let recoveryStarted = false;

export function PendingPromptRecovery(): null {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    // Re-arm on logout so a fresh session recovers again without a full app
    // restart (an orphaned prompt outlives logout in storage).
    if (!isAuthenticated) {
      recoveryStarted = false;
      return;
    }
    if (recoveryStarted) return;
    recoveryStarted = true;
    void recoverNewestPrompt();
  }, [isAuthenticated]);

  return null;
}

async function recoverNewestPrompt(): Promise<void> {
  await pendingPromptRecoveryStoreApi.whenHydrated();
  const [newest] = pendingPromptRecoveryStoreApi.getAllNewestFirst();
  if (!newest) return;

  log.info("Recovering a prompt whose task never finished creating");
  pendingPromptRecoveryStoreApi.clear(newest.key);
  router.push({
    pathname: "/task",
    params: { prompt: newest.prompt.promptText },
  });
}
