import { createAppendOnlyTracker } from "@posthog/core/sessions/appendOnlyTracker";
import {
  type AcpMessage,
  isJsonRpcNotification,
  readMcpToolDescriptor,
} from "@posthog/shared";
import { useMemo, useRef } from "react";

const UPLOAD_ARTIFACT_TOOL = "upload_artifact";

interface ArtifactUploadState {
  /** Tool calls identified as an artifact upload, by tool call id. */
  uploadCallIds: Set<string>;
  completedCallIds: Set<string>;
}

/**
 * Counts the artifact uploads that have finished this session, from the agent's
 * own `upload_artifact` tool calls.
 *
 * The run's manifest is server state, and the endpoint that serves it is not
 * pushed to, so this count is what tells a reader an upload landed — without it
 * a freshly delivered file waits for the next poll.
 */
export function createArtifactUploadTracker() {
  return createAppendOnlyTracker<ArtifactUploadState, number>({
    init: () => ({ uploadCallIds: new Set(), completedCallIds: new Set() }),
    processEvent: (state, event) => {
      const msg = event.message;
      if (!isJsonRpcNotification(msg)) return;
      if (msg.method !== "session/update") return;

      const update = (
        msg.params as
          | {
              update?: {
                sessionUpdate?: string;
                toolCallId?: string;
                status?: string;
                _meta?: unknown;
              };
            }
          | undefined
      )?.update;
      if (
        !update?.toolCallId ||
        (update.sessionUpdate !== "tool_call" &&
          update.sessionUpdate !== "tool_call_update")
      ) {
        return;
      }

      if (readMcpToolDescriptor(update._meta)?.tool === UPLOAD_ARTIFACT_TOOL) {
        state.uploadCallIds.add(update.toolCallId);
      }
      // A completion only counts once the call is known to be an upload, and the
      // id keeps a re-sent update from counting twice.
      if (
        update.status === "completed" &&
        state.uploadCallIds.has(update.toolCallId)
      ) {
        state.completedCallIds.add(update.toolCallId);
      }
    },
    getResult: (state) => state.completedCallIds.size,
  });
}

export function countCompletedArtifactUploads(events: AcpMessage[]): number {
  return createArtifactUploadTracker().update(events);
}

export function useCompletedArtifactUploads(events: AcpMessage[]): number {
  const trackerRef = useRef<ReturnType<
    typeof createArtifactUploadTracker
  > | null>(null);
  trackerRef.current ??= createArtifactUploadTracker();
  const tracker = trackerRef.current;
  return useMemo(() => tracker.update(events), [events, tracker]);
}
