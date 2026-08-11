import { Button, Flex, Text, TextField } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { type IpcTimingEntry, useIpcMetricsStore } from "../ipcMetricsStore";

const MAX_DISPLAY = 400;

interface IpcTimingsPanelProps {
  enabled: boolean;
}

export function IpcTimingsPanel({ enabled }: IpcTimingsPanelProps) {
  const entries = useIpcMetricsStore((s) => s.entries);
  const inFlight = useIpcMetricsStore((s) => s.inFlight);
  const peakInFlight = useIpcMetricsStore((s) => s.peakInFlight);
  const clear = useIpcMetricsStore((s) => s.clear);
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    const lower = filter.trim().toLowerCase();
    const rows = lower
      ? entries.filter((t) => t.path.toLowerCase().includes(lower))
      : entries;
    return rows.slice(-MAX_DISPLAY).reverse();
  }, [entries, filter]);

  const aggregates = useMemo(() => {
    const map = new Map<
      string,
      {
        count: number;
        totalRtt: number;
        maxRtt: number;
        totalBytes: number;
      }
    >();
    for (const t of entries) {
      const cur = map.get(t.path) ?? {
        count: 0,
        totalRtt: 0,
        maxRtt: 0,
        totalBytes: 0,
      };
      cur.count += 1;
      cur.totalRtt += t.rttMs;
      cur.maxRtt = Math.max(cur.maxRtt, t.rttMs);
      cur.totalBytes += t.inputBytes + t.outputBytes;
      map.set(t.path, cur);
    }
    return [...map.entries()]
      .map(([path, v]) => ({
        path,
        ...v,
        avgRtt: v.totalRtt / v.count,
      }))
      .sort((a, b) => b.totalRtt - a.totalRtt)
      .slice(0, 12);
  }, [entries]);

  if (!enabled) {
    return (
      <Flex align="center" justify="center" className="h-full">
        <Text size="1" color="gray">
          Enable dev mode to capture IPC traffic.
        </Text>
      </Flex>
    );
  }

  return (
    <Flex direction="column" gap="2" className="h-full overflow-hidden p-3">
      <Flex gap="2" align="center" wrap="wrap">
        <TextField.Root
          size="1"
          placeholder="Filter by path..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="flex-1"
        />
        <Button size="1" variant="soft" onClick={clear}>
          Clear
        </Button>
        <StatChip label="Captured" value={entries.length.toString()} />
        <StatChip
          label="In flight"
          value={inFlight.toString()}
          tone={inFlight > 5 ? "amber" : undefined}
        />
        <StatChip
          label="Peak"
          value={peakInFlight.toString()}
          tone={peakInFlight > 10 ? "amber" : undefined}
        />
      </Flex>

      <Flex gap="4" className="overflow-hidden" flexGrow="1">
        <Flex direction="column" gap="1" className="w-1/2 overflow-y-auto">
          <Text size="1" weight="medium" color="gray">
            Recent
          </Text>
          <div className="grid grid-cols-[1fr_44px_70px_80px] gap-x-3 gap-y-0.5 font-mono text-[11px]">
            <Text size="1" color="gray" weight="medium">
              Path
            </Text>
            <Text size="1" color="gray" weight="medium">
              Type
            </Text>
            <Text size="1" color="gray" weight="medium">
              RTT
            </Text>
            <Text size="1" color="gray" weight="medium" className="text-right">
              Payload
            </Text>
            {filtered.map((t) => (
              <TimingRow key={t.id} timing={t} />
            ))}
          </div>
        </Flex>

        <Flex direction="column" gap="1" className="w-1/2 overflow-y-auto">
          <Text size="1" weight="medium" color="gray">
            Top by total RTT
          </Text>
          <div className="grid grid-cols-[1fr_44px_60px_60px_70px] gap-x-3 gap-y-0.5 font-mono text-[11px]">
            <Text size="1" color="gray" weight="medium">
              Path
            </Text>
            <Text size="1" color="gray" weight="medium">
              Count
            </Text>
            <Text size="1" color="gray" weight="medium">
              Avg
            </Text>
            <Text size="1" color="gray" weight="medium">
              Max
            </Text>
            <Text size="1" color="gray" weight="medium" className="text-right">
              Bytes
            </Text>
            {aggregates.map((a) => (
              <AggregateRow key={a.path} {...a} />
            ))}
          </div>
        </Flex>
      </Flex>
    </Flex>
  );
}

function TimingRow({ timing }: { timing: IpcTimingEntry }) {
  const tone = rttTone(timing.rttMs);
  return (
    <>
      <Text size="1" className="truncate" color={timing.ok ? undefined : "red"}>
        {timing.path}
      </Text>
      <Text size="1" color="gray">
        {abbreviateType(timing.type)}
      </Text>
      <Text size="1" color={tone}>
        {formatRtt(timing.rttMs)}
      </Text>
      <Text size="1" color="gray" className="text-right">
        {formatBytes(timing.inputBytes + timing.outputBytes)}
      </Text>
    </>
  );
}

function AggregateRow({
  path,
  count,
  avgRtt,
  maxRtt,
  totalBytes,
}: {
  path: string;
  count: number;
  avgRtt: number;
  maxRtt: number;
  totalBytes: number;
}) {
  return (
    <>
      <Text size="1" className="truncate">
        {path}
      </Text>
      <Text size="1">{count}</Text>
      <Text size="1" color={rttTone(avgRtt)}>
        {formatRtt(avgRtt)}
      </Text>
      <Text size="1" color={rttTone(maxRtt)}>
        {formatRtt(maxRtt)}
      </Text>
      <Text size="1" color="gray" className="text-right">
        {formatBytes(totalBytes)}
      </Text>
    </>
  );
}

function StatChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "amber" | "red";
}) {
  const color =
    tone === "red"
      ? "text-(--red-11) bg-(--red-3)"
      : tone === "amber"
        ? "text-(--amber-11) bg-(--amber-3)"
        : "text-(--gray-11) bg-(--gray-3)";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px] ${color}`}
    >
      <span className="uppercase opacity-70">{label}</span>
      <span className="font-medium">{value}</span>
    </span>
  );
}

function formatRtt(ms: number): string {
  if (ms < 1) return `${(ms * 1000).toFixed(0)}μs`;
  if (ms < 10) return `${ms.toFixed(2)}ms`;
  if (ms < 100) return `${ms.toFixed(1)}ms`;
  return `${ms.toFixed(0)}ms`;
}

function rttTone(ms: number): "red" | "amber" | undefined {
  if (ms > 200) return "red";
  if (ms > 50) return "amber";
  return undefined;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(2)}MB`;
}

function abbreviateType(t: IpcTimingEntry["type"]): string {
  if (t === "query") return "q";
  if (t === "mutation") return "m";
  return "sub";
}
