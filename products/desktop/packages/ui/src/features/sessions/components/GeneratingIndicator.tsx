import { Brain, Circle } from "@phosphor-icons/react";
import {
  pickNextThinkingActivity,
  pickThinkingActivity,
} from "@posthog/core/sessions/thinkingActivities";
import { Text } from "@posthog/quill";
import { useEffect, useRef, useState } from "react";

function getRandomThinkingMessage(): string {
  return pickThinkingActivity(Math.random());
}

/** Pick a new word that differs from the current one, so consecutive changes
 *  always read as a change. */
function getNextThinkingMessage(current: string): string {
  return pickNextThinkingActivity(current, Math.random());
}

/** How long the thread has to stay silent before the hint says so. Long enough
 *  that a normally chatty turn never trips it, short enough to land well inside
 *  a slow tool call. */
const QUIET_AFTER_MS = 10_000;

export function formatDuration(ms: number, fractionDigits = 2): string {
  const totalSeconds = Math.floor(ms / 1000);
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;

  if (mins > 0) {
    return `${mins}m ${secs.toString().padStart(2, "0")}s`;
  }

  if (fractionDigits <= 0) {
    return `${secs}s`;
  }

  const fractionalUnit = 10 ** (3 - fractionDigits);
  const fractionalValue = Math.floor((ms % 1000) / fractionalUnit);

  return `${secs}.${fractionalValue.toString().padStart(fractionDigits, "0")}s`;
}

interface GeneratingIndicatorProps {
  /** Timestamp (ms) when the prompt started. Only render this component while a prompt is pending. */
  startedAt?: number | null;
  /** Accumulated time (ms) spent waiting for user input, subtracted from elapsed display. */
  pausedDurationMs?: number;
  /** Monotonic counter of finished tool/MCP calls. The status word advances
   *  each time this changes, so it tracks real work completing rather than a
   *  timer — a stalled agent keeps the same word. */
  activityKey?: number;
  /** Timestamp (ms) of the newest event in the thread. Once it falls far enough
   *  behind, the hint adds a ticking "quiet for Ns" so a turn that renders
   *  nothing for minutes still reads as running rather than hung. */
  lastActivityAt?: number | null;
}

export function GeneratingIndicator({
  startedAt,
  pausedDurationMs,
  activityKey,
  lastActivityAt,
}: GeneratingIndicatorProps) {
  const [elapsed, setElapsed] = useState(0);
  const [quietFor, setQuietFor] = useState(0);
  const [activity, setActivity] = useState(getRandomThinkingMessage);

  const pausedRef = useRef(pausedDurationMs ?? 0);
  pausedRef.current = pausedDurationMs ?? 0;
  const lastActivityRef = useRef(lastActivityAt ?? null);
  lastActivityRef.current = lastActivityAt ?? null;

  useEffect(() => {
    const startTime = startedAt ?? Date.now();
    const interval = setInterval(() => {
      const now = Date.now();
      setElapsed(Math.max(0, now - startTime - pausedRef.current));
      // Measured from the last event rather than the turn's start, so a turn
      // that streamed for a minute and then went silent still reads as quiet.
      const since = lastActivityRef.current;
      setQuietFor(since === null ? 0 : Math.max(0, now - since));
    }, 100);

    return () => clearInterval(interval);
  }, [startedAt]);

  // Advance the word only when a tool/MCP call finishes (activityKey changes),
  // not on an interval. The initial word stays put until the first call settles.
  // Adjusted during render (React's blessed pattern for deriving state from a
  // changed prop) rather than in an effect, so it never paints a stale word.
  const prevActivityKeyRef = useRef(activityKey);
  if (activityKey !== undefined && activityKey !== prevActivityKeyRef.current) {
    prevActivityKeyRef.current = activityKey;
    setActivity((current) => getNextThinkingMessage(current));
  }

  const dot = (
    <Circle
      size={4}
      weight="fill"
      className="mx-1 inline-block align-middle text-gray-9"
    />
  );

  return (
    <div
      className="flex min-w-0 select-none items-center gap-2"
      style={{ WebkitUserSelect: "none" }}
    >
      <Brain size={12} className="ph-pulse shrink-0" />
      <Text render={<span />} className="truncate text-[13px] text-accent-11">
        {activity}...
      </Text>
      {/* The hint shrinks (and truncates) well before the activity word does. */}
      <Text
        render={<span />}
        className="shrink-[8] truncate text-(--gray-11) text-[13px]"
      >
        (Esc to stop
        {dot}
        <span style={{ fontVariantNumeric: "tabular-nums" }}>
          {formatDuration(elapsed, 1)}
        </span>
        {quietFor >= QUIET_AFTER_MS && (
          <>
            {dot}
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              quiet for {formatDuration(quietFor, 0)}
            </span>
          </>
        )}
        )
      </Text>
    </div>
  );
}
