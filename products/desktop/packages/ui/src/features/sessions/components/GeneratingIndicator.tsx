import { Brain, Circle } from "@phosphor-icons/react";
import { Flex, Text } from "@radix-ui/themes";
import { useEffect, useRef, useState } from "react";

const THINKING_MESSAGES = [
  "Booping",
  "Crunching",
  "Digging",
  "Fetching",
  "Inferring",
  "Indexing",
  "Juggling",
  "Noodling",
  "Peeking",
  "Percolating",
  "Poking",
  "Pondering",
  "Scanning",
  "Scrambling",
  "Sifting",
  "Sniffing",
  "Spelunking",
  "Tinkering",
  "Unraveling",
  "Decoding",
  "Trekking",
  "Sorting",
  "Trimming",
  "Mulling",
  "Surfacing",
  "Rummaging",
  "Scouting",
  "Scouring",
  "Threading",
  "Hunting",
  "Swizzling",
  "Grokking",
  "Hedging",
  "Scheming",
  "Unfurling",
  "Puzzling",
  "Dissecting",
  "Stacking",
  "Snuffling",
  "Hashing",
  "Clustering",
  "Teasing",
  "Cranking",
  "Merging",
  "Snooping",
  "Rewiring",
  "Bundling",
  "Linking",
  "Mapping",
  "Tickling",
  "Flicking",
  "Hopping",
  "Rolling",
  "Zipping",
  "Twisting",
  "Blooming",
  "Sparking",
  "Nesting",
  "Looping",
  "Wiring",
  "Snipping",
  "Zoning",
  "Tracing",
  "Warping",
  "Twinkling",
  "Flipping",
  "Priming",
  "Snagging",
  "Scuttling",
  "Framing",
  "Sharpening",
  "Flibbertigibbeting",
  "Kerfuffling",
  "Dithering",
  "Discombobulating",
  "Rambling",
  "Befuddling",
  "Waffling",
  "Muckling",
  "Hobnobbing",
  "Galumphing",
  "Puttering",
  "Whiffling",
  "Thinking",
];

function getRandomThinkingMessage(): string {
  return THINKING_MESSAGES[
    Math.floor(Math.random() * THINKING_MESSAGES.length)
  ];
}

/** Pick a new word that differs from the current one, so consecutive changes
 *  always read as a change. */
function getNextThinkingMessage(current: string): string {
  if (THINKING_MESSAGES.length <= 1) return THINKING_MESSAGES[0];
  let next = current;
  while (next === current) {
    next =
      THINKING_MESSAGES[Math.floor(Math.random() * THINKING_MESSAGES.length)];
  }
  return next;
}

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
}

export function GeneratingIndicator({
  startedAt,
  pausedDurationMs,
  activityKey,
}: GeneratingIndicatorProps) {
  const [elapsed, setElapsed] = useState(0);
  const [activity, setActivity] = useState(getRandomThinkingMessage);

  const pausedRef = useRef(pausedDurationMs ?? 0);
  pausedRef.current = pausedDurationMs ?? 0;

  useEffect(() => {
    const startTime = startedAt ?? Date.now();
    const interval = setInterval(() => {
      setElapsed(Math.max(0, Date.now() - startTime - pausedRef.current));
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

  return (
    <Flex
      align="center"
      gap="2"
      className="min-w-0 select-none"
      style={{ WebkitUserSelect: "none" }}
    >
      <Brain size={12} className="ph-pulse shrink-0" />
      <Text className="truncate text-[13px] text-accent-11">{activity}...</Text>
      {/* The hint shrinks (and truncates) well before the activity word does. */}
      <Text color="gray" className="shrink-[8] truncate text-[13px]">
        (Esc to stop
        <Circle
          size={4}
          weight="fill"
          className="mx-1 inline-block align-middle text-gray-9"
        />
        <span style={{ fontVariantNumeric: "tabular-nums" }}>
          {formatDuration(elapsed, 1)})
        </span>
      </Text>
    </Flex>
  );
}
