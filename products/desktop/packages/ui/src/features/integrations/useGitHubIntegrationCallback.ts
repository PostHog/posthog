import { classifyGithubCallback } from "@posthog/core/integrations/connectEligibility";
import type { IntegrationCallback } from "@posthog/core/integrations/github";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { logger } from "@posthog/ui/shell/logger";
import { useEffect, useRef } from "react";

const log = logger.scope("github-integration-callback-hook");

const DEFAULT_ERROR_MESSAGE =
  "GitHub install failed. Please try connecting again.";

export interface IntegrationCallbackError {
  message: string;
  code: string | null;
}

interface Options {
  onSuccess: (projectId: number | null) => void;
  onError: (error: IntegrationCallbackError) => void;
  /** GitHub handed the install to an org owner; not an error, so it gets its own branch. */
  onPending?: (error: IntegrationCallbackError) => void;
  onTimedOut?: () => void;
}

type CallbackData = Pick<
  IntegrationCallback,
  "status" | "projectId" | "errorCode" | "errorMessage"
>;

function dispatchCallback(data: CallbackData, opts: Options): void {
  if (data.status !== "error") {
    opts.onSuccess(data.projectId);
    return;
  }
  const error: IntegrationCallbackError = {
    message: data.errorMessage ?? DEFAULT_ERROR_MESSAGE,
    code: data.errorCode,
  };
  if (
    classifyGithubCallback(data.errorCode) === "pending_org_approval" &&
    opts.onPending
  ) {
    opts.onPending(error);
    return;
  }
  opts.onError(error);
}

/**
 * Subscribes to GitHub integration deep link callbacks and drains any pending
 * callback that arrived before the subscription was established (cold-start).
 */
export function useGitHubIntegrationCallback({
  onSuccess,
  onError,
  onPending,
  onTimedOut,
}: Options): void {
  const client = useHostTRPCClient();
  const hasConsumedPendingRef = useRef(false);

  const optsRef = useRef({ onSuccess, onError, onPending, onTimedOut });
  // Declared before the subscription effects so the commit order keeps the ref ahead of them.
  useEffect(() => {
    optsRef.current = { onSuccess, onError, onPending, onTimedOut };
  });

  useEffect(() => {
    const callbackSubscription = client.githubIntegration.onCallback.subscribe(
      undefined,
      {
        onData: (data) => {
          log.info("Received integration deep link callback", data);
          dispatchCallback(data, optsRef.current);
        },
      },
    );

    const timedOutSubscription =
      client.githubIntegration.onFlowTimedOut.subscribe(undefined, {
        onData: (data) => {
          log.info("GitHub integration flow timed out", data);
          optsRef.current.onTimedOut?.();
        },
      });

    return () => {
      callbackSubscription.unsubscribe();
      timedOutSubscription.unsubscribe();
    };
  }, [client]);

  useEffect(() => {
    if (hasConsumedPendingRef.current) return;
    hasConsumedPendingRef.current = true;
    void (async () => {
      try {
        const pending =
          await client.githubIntegration.consumePendingCallback.query();
        if (!pending) return;
        log.info("Consumed pending integration callback on mount", pending);
        dispatchCallback(pending, optsRef.current);
      } catch (error) {
        log.error("Failed to consume pending integration callback", error);
      }
    })();
  }, [client]);
}
