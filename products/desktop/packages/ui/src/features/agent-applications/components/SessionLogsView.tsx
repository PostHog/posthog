import { formatRelativeTimeShort } from "@posthog/shared";
import type { AgentSessionLogEntry } from "@posthog/shared/agent-platform-types";
import { Flex, Text, TextField } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { useAgentApplicationSessionLogs } from "../hooks/useAgentApplicationSessionLogs";
import { formatDuration, logLevelColor } from "../utils/format";

type LevelFilter = "all" | "DEBUG" | "INFO" | "WARN" | "ERROR";

const LEVELS: LevelFilter[] = ["all", "DEBUG", "INFO", "WARN", "ERROR"];

/** Relative offset from session start ("+1.2s"), falling back to a clock label. */
function offsetLabel(startIso: string, ts: string): string {
  const d = formatDuration(startIso, ts);
  return d === "—" ? formatRelativeTimeShort(ts) : `+${d}`;
}

/**
 * Structured runtime log viewer for one session: level dot, offset from session
 * start, message. Level + substring filtering is client-side over the fetched
 * page (the API also filters server-side, but a page is small enough to scan).
 */
export function SessionLogsView({
  idOrSlug,
  sessionId,
  startIso,
  enabled,
}: {
  idOrSlug: string;
  sessionId: string;
  startIso: string;
  enabled: boolean;
}) {
  const [level, setLevel] = useState<LevelFilter>("all");
  const [search, setSearch] = useState("");

  const { data, isLoading, isError } = useAgentApplicationSessionLogs(
    idOrSlug,
    sessionId,
    { enabled, params: { limit: 200 } },
  );

  const filtered = useMemo(() => {
    const entries = data ?? [];
    const q = search.trim().toLowerCase();
    return entries.filter((e) => {
      if (level !== "all" && e.level.toUpperCase() !== level) return false;
      if (q && !e.message.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [data, level, search]);

  return (
    <Flex direction="column" gap="3" className="mx-auto max-w-4xl px-6 py-5">
      <Flex align="center" gap="3" wrap="wrap" justify="between">
        <Flex gap="1.5" wrap="wrap">
          {LEVELS.map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setLevel(l)}
              className={`rounded-full border px-2.5 py-0.5 text-[11px] uppercase ${
                level === l
                  ? "border-(--accent-7) bg-(--accent-3) text-gray-12"
                  : "border-border text-gray-11 hover:border-(--gray-7)"
              }`}
            >
              {l === "all" ? "All" : l}
            </button>
          ))}
        </Flex>
        <TextField.Root
          size="1"
          placeholder="Search messages"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-48"
        />
      </Flex>

      {isLoading ? (
        <Flex direction="column" gap="1">
          {[0, 1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-6 animate-pulse rounded-(--radius-1) bg-(--gray-2)"
            />
          ))}
        </Flex>
      ) : isError ? (
        <Text className="text-[12px] text-gray-11">
          Couldn't load logs for this session.
        </Text>
      ) : filtered.length === 0 ? (
        <Text className="text-[12px] text-gray-10">
          {(data?.length ?? 0) === 0
            ? "No logs recorded for this session."
            : "No logs match the current filter."}
        </Text>
      ) : (
        <div className="overflow-hidden rounded-(--radius-2) border border-border">
          {filtered.map((entry, i) => (
            <LogRow
              key={`${entry.timestamp}-${i}`}
              entry={entry}
              startIso={startIso}
              last={i === filtered.length - 1}
            />
          ))}
        </div>
      )}
    </Flex>
  );
}

function LogRow({
  entry,
  startIso,
  last,
}: {
  entry: AgentSessionLogEntry;
  startIso: string;
  last: boolean;
}) {
  return (
    <Flex
      align="start"
      gap="3"
      className={`px-3 py-1.5 ${last ? "" : "border-(--gray-4) border-b"} hover:bg-(--gray-2)`}
    >
      <span
        className="mt-1.5 size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: logLevelColor(entry.level) }}
      />
      <Text className="w-14 shrink-0 text-[11px] text-gray-10 tabular-nums [font-family:var(--font-mono)]">
        {offsetLabel(startIso, entry.timestamp)}
      </Text>
      <Text className="min-w-0 whitespace-pre-wrap break-words text-[12px] text-gray-12 [font-family:var(--font-mono)]">
        {entry.message}
      </Text>
    </Flex>
  );
}
