import {
  Button,
  Flex,
  Select,
  Switch,
  Text,
  TextField,
} from "@radix-ui/themes";
import { trpcClient, useTRPC } from "@renderer/trpc/client";
import { useSubscription } from "@trpc/tanstack-react-query";
import { Copy, Pause, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { LogEntry } from "../../../../main/services/dev-logs/schemas";

const MAX_DISPLAY = 1000;
const LEVELS = ["error", "warn", "info", "debug", "verbose", "silly"] as const;
type LevelFilter = "all" | (typeof LEVELS)[number];

interface LogsPanelProps {
  enabled: boolean;
}

export function LogsPanel({ enabled }: LogsPanelProps) {
  const trpcReact = useTRPC();
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState("");
  const [levelFilter, setLevelFilter] = useState<LevelFilter>("all");
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void trpcClient.dev.getLogs.query().then((snap) => {
      if (!cancelled) setEntries(snap.entries);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  useSubscription(
    trpcReact.dev.onLogEntry.subscriptionOptions(undefined, {
      enabled: enabled && !paused,
      onData: (entry) => {
        setEntries((prev) => {
          const next = [...prev, entry];
          return next.length > MAX_DISPLAY
            ? next.slice(next.length - MAX_DISPLAY)
            : next;
        });
      },
    }),
  );

  const filtered = useMemo(() => {
    const lower = filter.trim().toLowerCase();
    return entries.filter((e) => {
      if (levelFilter !== "all" && e.level !== levelFilter) return false;
      if (lower) {
        if (
          !e.message.toLowerCase().includes(lower) &&
          !(e.scope?.toLowerCase().includes(lower) ?? false)
        ) {
          return false;
        }
      }
      return true;
    });
  }, [entries, filter, levelFilter]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on new entries
  useEffect(() => {
    if (!autoScroll || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [filtered.length, autoScroll]);

  const copyAsJsonl = () => {
    const jsonl = filtered.map((e) => JSON.stringify(e)).join("\n");
    void navigator.clipboard.writeText(jsonl);
  };

  return (
    <Flex direction="column" gap="2" className="h-full overflow-hidden p-3">
      <Flex gap="2" align="center" wrap="wrap">
        <TextField.Root
          size="1"
          placeholder="Filter message or scope..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="min-w-[180px] flex-1"
        />
        <Select.Root
          size="1"
          value={levelFilter}
          onValueChange={(v) => setLevelFilter(v as LevelFilter)}
        >
          <Select.Trigger />
          <Select.Content>
            <Select.Item value="all">All levels</Select.Item>
            {LEVELS.map((l) => (
              <Select.Item key={l} value={l}>
                {l}
              </Select.Item>
            ))}
          </Select.Content>
        </Select.Root>
        <Button
          size="1"
          variant="soft"
          onClick={() => setPaused((p) => !p)}
          color={paused ? "amber" : undefined}
        >
          {paused ? <Play size={12} /> : <Pause size={12} />}
          {paused ? "Resume" : "Pause"}
        </Button>
        <Flex align="center" gap="1">
          <Switch
            size="1"
            checked={autoScroll}
            onCheckedChange={setAutoScroll}
          />
          <Text size="1">Follow</Text>
        </Flex>
        <Button size="1" variant="soft" onClick={copyAsJsonl}>
          <Copy size={12} /> Copy
        </Button>
        <Button
          size="1"
          variant="soft"
          onClick={async () => {
            await trpcClient.dev.clearLogs.mutate();
            setEntries([]);
          }}
        >
          Clear
        </Button>
        <Button
          size="1"
          variant="soft"
          onClick={() => void trpcClient.dev.openLogFile.mutate()}
        >
          Open file
        </Button>
        <Text size="1" color="gray" className="font-mono">
          {filtered.length}/{entries.length}
        </Text>
      </Flex>

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto rounded-md border border-(--gray-5) bg-(--gray-1)"
      >
        <div className="grid grid-cols-[60px_55px_90px_1fr] gap-x-2 font-mono text-[11px]">
          {filtered.map((entry) => (
            <LogRow key={entry.id} entry={entry} />
          ))}
        </div>
      </div>
    </Flex>
  );
}

function LogRow({ entry }: { entry: LogEntry }) {
  const date = new Date(entry.capturedAt);
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
    date.getSeconds(),
  )}`;
  const levelColor =
    entry.level === "error"
      ? "text-(--red-11)"
      : entry.level === "warn"
        ? "text-(--amber-11)"
        : entry.level === "debug" || entry.level === "verbose"
          ? "text-(--gray-10)"
          : "text-(--gray-12)";
  return (
    <>
      <span className="px-2 py-0.5 text-(--gray-10)">{time}</span>
      <span className={`py-0.5 ${levelColor}`}>{entry.level}</span>
      <span className="truncate py-0.5 text-(--gray-11)" title={entry.scope}>
        {entry.scope ?? "—"}
      </span>
      <span className="break-words py-0.5 pr-2 text-(--gray-12)">
        {entry.message}
      </span>
    </>
  );
}

function pad(n: number): string {
  return n.toString().padStart(2, "0");
}
