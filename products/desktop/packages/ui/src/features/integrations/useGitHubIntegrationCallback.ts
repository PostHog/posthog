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
  onTimedOut?: () => void;
}

/**
 * Subscribes to GitHub integration deep link callbacks and drains any pending
 * callback that arrived before the subscription was established (cold-start).
 */
export function useGitHubIntegrationCallback({
  onSuccess,
  onError,
  onTimedOut,
}: Options): void {
  const client = useHostTRPCClient();
  const hasConsumedPendingRef = useRef(false);

  const optsRef = useRef({ onSuccess, onError, onTimedOut });
  optsRef.current = { onSuccess, onError, onTimedOut };

  useEffect(() => {
    const callbackSubscription = client.githubIntegration.onCallback.subscribe(
      undefined,
      {
        onData: (data) => {
          log.info("Received integration deep link callback", data);
          if (data.status === "error") {
            optsRef.current.onError({
              message: data.errorMessage ?? DEFAULT_ERROR_MESSAGE,
              code: data.errorCode,
            });
            return;
          }
          optsRef.current.onSuccess(data.projectId);
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
        if (pending.status === "error") {
          optsRef.current.onError({
            message: pending.errorMessage ?? DEFAULT_ERROR_MESSAGE,
            code: pending.errorCode,
          });
          return;
        }
        optsRef.current.onSuccess(pending.projectId);
      } catch (error) {
        log.error("Failed to consume pending integration callback", error);
      }
    })();
  }, [client]);
}
