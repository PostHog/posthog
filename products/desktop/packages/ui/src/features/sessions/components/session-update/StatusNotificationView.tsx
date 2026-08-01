import {
  ArrowsClockwise,
  ShieldWarning,
  Spinner,
  XCircle,
} from "@phosphor-icons/react";
import { ChatMarker, ChatMarkerContent } from "@posthog/quill";
import { Box, Callout, Flex, Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";
import { formatDuration } from "../GeneratingIndicator";

interface StatusNotificationViewProps {
  status: string;
  isComplete?: boolean;
  /** Epoch ms when a `compacting` status began; anchors the elapsed timer so it
   *  survives unmount/remount in the virtualized list instead of resetting. */
  startedAt?: number;
  /** Failure reason, set on a `compacting_failed` status. */
  error?: string;
  /** Refusal statuses: display-only stop_details.explanation from the API. */
  explanation?: string;
  /** Refusal fallback: the model that declined the request. */
  fromModel?: string;
  /** Refusal fallback: the model that retried the request. */
  toModel?: string;
  message?: string;
  attempt?: number;
  maxAttempts?: number;
  delayMs?: number;
}

export function formatCompactionFailure(error?: string): string {
  const detail = error?.replace(/^compaction failed:\s*/i, "");
  return detail ? `Compacting failed: ${detail}` : "Compacting failed";
}

export function StatusNotificationView({
  status,
  isComplete,
  startedAt,
  error,
  explanation,
  fromModel,
  toModel,
  message,
  attempt,
  maxAttempts,
  delayMs,
}: StatusNotificationViewProps) {
  // New thread renders status notes as centered separator markers; the legacy thread keeps its
  // bordered rows so ConversationView is unchanged when the chat thread is off.
  const chatChrome = useChatThreadChrome();

  // Terminal refusal: the safety classifier declined the request and no
  // fallback model rescued it. Rendered as a callout in both chromes.
  if (status === "refusal") {
    return (
      <Box className="my-2">
        <Callout.Root color="orange" size="1">
          <Callout.Icon>
            <ShieldWarning weight="fill" />
          </Callout.Icon>
          <Callout.Text>
            <Flex direction="column" gap="1">
              <Text className="font-medium text-sm">
                Claude declined to continue with this request.
              </Text>
              {explanation && (
                <Text className="text-[13px] text-gray-11">{explanation}</Text>
              )}
              <Text className="text-[13px] text-gray-11">
                Try rephrasing your request, or switch models and retry.
              </Text>
            </Flex>
          </Callout.Text>
        </Callout.Root>
      </Box>
    );
  }

  if (status === "refusal_fallback") {
    const message =
      fromModel && toModel
        ? `${fromModel} declined this request, retried with ${toModel}`
        : "Request declined, retried with the fallback model";
    if (chatChrome) {
      return (
        <ChatMarker variant="separator">
          <ChatMarkerContent>{message}</ChatMarkerContent>
        </ChatMarker>
      );
    }
    return (
      <Box className="my-1 border-orange-6 border-l-2 py-1 pl-3 dark:border-orange-8">
        <Flex align="center" gap="2">
          <ArrowsClockwise size={14} className="text-orange-9" />
          <Text className="text-[13px] text-gray-11">{message}</Text>
        </Flex>
      </Box>
    );
  }

  // A failed compaction (e.g. "Not enough messages to compact"). The matching `compacting` spinner
  // is cleared separately; this row reports the outcome.
  if (status === "compacting_failed") {
    const failureMessage = formatCompactionFailure(error);
    if (chatChrome) {
      return (
        <ChatMarker variant="separator">
          <ChatMarkerContent>{failureMessage}</ChatMarkerContent>
        </ChatMarker>
      );
    }
    return (
      <Box className="my-1 border-gray-6 border-l-2 py-1 pl-3 dark:border-gray-8">
        <Flex align="center" gap="2">
          <XCircle size={14} className="text-gray-9" />
          <Text className="text-[13px] text-gray-11">{failureMessage}</Text>
        </Flex>
      </Box>
    );
  }

  if (status === "compacting") {
    if (isComplete) {
      return null;
    }
    return <CompactingStatusView startedAt={startedAt} />;
  }

  if (status === "retrying") {
    if (isComplete) {
      return null;
    }
    return (
      <RetryingStatusView
        startedAt={startedAt}
        delayMs={delayMs}
        attempt={attempt}
        maxAttempts={maxAttempts}
        message={message}
      />
    );
  }

  // Generic status display for other statuses
  return (
    <Box className="my-1 border-gray-6 border-l-2 py-1 pl-3 dark:border-gray-8">
      <Flex align="center" gap="2">
        <Text className="text-[13px] text-gray-11">Status: {status}</Text>
      </Flex>
    </Box>
  );
}

function RetryingStatusView({
  startedAt,
  delayMs = 0,
  attempt,
  maxAttempts,
  message,
}: {
  startedAt?: number;
  delayMs?: number;
  attempt?: number;
  maxAttempts?: number;
  message?: string;
}) {
  const [remainingMs, setRemainingMs] = useState(delayMs);

  useEffect(() => {
    const start = startedAt ?? Date.now();
    const tick = () => {
      setRemainingMs(Math.max(0, delayMs - (Date.now() - start)));
    };
    tick();
    const interval = setInterval(tick, 100);
    return () => clearInterval(interval);
  }, [delayMs, startedAt]);

  const attemptLabel =
    attempt && maxAttempts
      ? `Attempt ${attempt} of ${maxAttempts}`
      : "Retrying";
  const retryLabel =
    remainingMs > 0
      ? `${attemptLabel} in ${formatDuration(remainingMs, 1)}`
      : `${attemptLabel} now`;

  return (
    <ChatMarker variant="separator">
      <ChatMarkerContent>
        <Flex align="center" gap="2">
          <ArrowsClockwise size={13} className="animate-spin text-amber-9" />
          <Text className="text-[13px] text-gray-11">{retryLabel}</Text>
          {message && (
            <Text className="truncate text-[13px] text-gray-10">{message}</Text>
          )}
        </Flex>
      </ChatMarkerContent>
    </ChatMarker>
  );
}

/**
 * In-flight compaction row. Compaction is a single streaming summarization call
 * with no measurable percentage, so we pair the spinner with an indeterminate
 * progress bar (constant motion, so it never reads as frozen) and a live
 * elapsed-time counter, which is the one honest progress signal we have.
 */
function CompactingStatusView({ startedAt }: { startedAt?: number }) {
  const [elapsed, setElapsed] = useState(() =>
    startedAt ? Date.now() - startedAt : 0,
  );

  useEffect(() => {
    // Anchor to the persisted compaction start time so remounting this row
    // (e.g. scrolling it out of and back into the virtualized list while
    // compaction runs) keeps counting from when compaction began rather than
    // resetting to zero. Fall back to mount time only if it's missing.
    const start = startedAt ?? Date.now();
    const tick = () => setElapsed(Date.now() - start);
    tick();
    const interval = setInterval(tick, 100);
    return () => clearInterval(interval);
  }, [startedAt]);

  return (
    <Box className="my-1 border-blue-6 border-l-2 px-3 py-1 dark:border-blue-8">
      <Flex align="center" gap="2">
        <Spinner size={14} className="animate-spin text-blue-9" />
        <Text className="text-[13px] text-gray-11">
          Compacting conversation history...
        </Text>
        <Text className="text-[13px] text-gray-10 tabular-nums">
          {formatDuration(elapsed, 1)}
        </Text>
      </Flex>
      {/* Decorative: the spinner and the text above carry the accessible status. */}
      <div className="compacting-progress mt-1.5" aria-hidden="true" />
    </Box>
  );
}
