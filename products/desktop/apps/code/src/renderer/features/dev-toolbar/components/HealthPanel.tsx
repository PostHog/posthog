import { Button, Flex, Text } from "@radix-ui/themes";
import { useTRPC } from "@renderer/trpc/client";
import { useSubscription } from "@trpc/tanstack-react-query";
import { Activity, Gauge, Timer } from "lucide-react";
import { useMemo, useState } from "react";
import type { MetricsSample } from "../../../../main/services/dev-metrics/schemas";
import { useMainThreadHealthStore } from "../mainThreadHealth";

const HISTORY_LENGTH = 60;

interface HealthPanelProps {
  enabled: boolean;
}

export function HealthPanel({ enabled }: HealthPanelProps) {
  const trpcReact = useTRPC();
  const [loopLagHistory, setLoopLagHistory] = useState<number[]>([]);
  const [loopLagMaxHistory, setLoopLagMaxHistory] = useState<number[]>([]);
  const fps = useMainThreadHealthStore((s) => s.fps);
  const longTasks = useMainThreadHealthStore((s) => s.longTasks);
  const longTaskCount = useMainThreadHealthStore((s) => s.longTaskCount);
  const resetLongTasks = useMainThreadHealthStore((s) => s.reset);

  useSubscription(
    trpcReact.dev.onMetrics.subscriptionOptions(undefined, {
      enabled,
      onData: (sample: MetricsSample) => {
        setLoopLagHistory((prev) =>
          appendHistory(prev, sample.loopLagMs, HISTORY_LENGTH),
        );
        setLoopLagMaxHistory((prev) =>
          appendHistory(prev, sample.loopLagMaxMs, HISTORY_LENGTH),
        );
      },
    }),
  );

  const loopLagCurrent = loopLagHistory[loopLagHistory.length - 1] ?? 0;
  const loopLagPeak = loopLagMaxHistory.length
    ? Math.max(...loopLagMaxHistory)
    : 0;

  const recentLongTasks = useMemo(
    () => [...longTasks].reverse().slice(0, 20),
    [longTasks],
  );

  return (
    <Flex direction="column" gap="3" className="h-full overflow-y-auto p-3">
      <div className="grid grid-cols-3 gap-3">
        <HealthCard
          icon={<Timer size={14} />}
          title="Main loop lag"
          value={`${loopLagCurrent.toFixed(0)}ms`}
          accent={
            loopLagCurrent > 50
              ? "red"
              : loopLagCurrent > 20
                ? "amber"
                : undefined
          }
          subline={`peak ${loopLagPeak.toFixed(0)}ms`}
          history={loopLagHistory}
          ymax={Math.max(20, loopLagPeak)}
        />
        <HealthCard
          icon={<Gauge size={14} />}
          title="Renderer FPS"
          value={`${fps}`}
          accent={fps < 30 ? "red" : fps < 50 ? "amber" : undefined}
          subline="last second"
          history={null}
          ymax={60}
        />
        <HealthCard
          icon={<Activity size={14} />}
          title="Long tasks"
          value={`${longTaskCount}`}
          accent={longTaskCount > 0 ? "amber" : undefined}
          subline="> 50ms blocking"
          history={null}
          ymax={1}
        />
      </div>

      <Flex direction="column" gap="1">
        <Flex justify="between" align="center">
          <Text size="1" weight="medium" color="gray">
            Recent long tasks (renderer)
          </Text>
          <Button size="1" variant="soft" onClick={resetLongTasks}>
            Reset
          </Button>
        </Flex>
        {recentLongTasks.length === 0 ? (
          <Text size="1" color="gray">
            None captured. Long tasks are renderer-blocking work over 50ms.
          </Text>
        ) : (
          <div className="grid grid-cols-[80px_1fr_80px] gap-x-3 gap-y-0.5 font-mono text-[11px]">
            <Text size="1" color="gray" weight="medium">
              Time
            </Text>
            <Text size="1" color="gray" weight="medium">
              Name
            </Text>
            <Text size="1" color="gray" weight="medium">
              Duration
            </Text>
            {recentLongTasks.map((t) => (
              <LongTaskRow key={t.id} {...t} />
            ))}
          </div>
        )}
      </Flex>
    </Flex>
  );
}

function LongTaskRow({
  durationMs,
  name,
  startedAt,
}: {
  durationMs: number;
  name: string;
  startedAt: number;
}) {
  const date = new Date(startedAt);
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
    date.getSeconds(),
  )}`;
  const color =
    durationMs > 200 ? "red" : durationMs > 100 ? "amber" : undefined;
  return (
    <>
      <Text size="1" color="gray">
        {time}
      </Text>
      <Text size="1" className="truncate">
        {name}
      </Text>
      <Text size="1" color={color}>
        {durationMs.toFixed(0)}ms
      </Text>
    </>
  );
}

interface HealthCardProps {
  icon: React.ReactNode;
  title: string;
  value: string;
  accent: "red" | "amber" | undefined;
  subline: string;
  history: number[] | null;
  ymax: number;
}

function HealthCard({
  icon,
  title,
  value,
  accent,
  subline,
  history,
  ymax,
}: HealthCardProps) {
  const valueColor =
    accent === "red"
      ? "text-(--red-11)"
      : accent === "amber"
        ? "text-(--amber-11)"
        : "text-(--gray-12)";
  const lineClass =
    accent === "red"
      ? "text-(--red-9)"
      : accent === "amber"
        ? "text-(--amber-9)"
        : "text-(--accent-9)";
  return (
    <div className="overflow-hidden rounded-md border border-(--gray-5) bg-(--gray-1)">
      <Flex
        align="center"
        gap="2"
        className="border-(--gray-5) border-b bg-(--gray-2) px-3 py-1.5"
      >
        <span className="text-(--gray-10)">{icon}</span>
        <Text size="1" weight="medium" className="text-(--gray-11) uppercase">
          {title}
        </Text>
      </Flex>
      <Flex direction="column" gap="2" className="p-3">
        <Text
          size="6"
          weight="bold"
          className={`font-mono leading-none ${valueColor}`}
        >
          {value}
        </Text>
        {history && history.length > 0 && (
          <Sparkline history={history} ymax={ymax} lineClass={lineClass} />
        )}
        <Text size="1" color="gray">
          {subline}
        </Text>
      </Flex>
    </div>
  );
}

function Sparkline({
  history,
  ymax,
  lineClass,
}: {
  history: number[];
  ymax: number;
  lineClass: string;
}) {
  const width = 200;
  const height = 36;
  const max = Math.max(1, ymax);
  const step = history.length > 1 ? width / (history.length - 1) : width;
  const points = history
    .map((v, i) => `${i * step},${height - (v / max) * (height - 4) - 2}`)
    .join(" ");
  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="history"
    >
      <title>history</title>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className={lineClass}
      />
    </svg>
  );
}

function appendHistory(prev: number[], value: number, max: number): number[] {
  const next = [...prev, value];
  return next.length > max ? next.slice(next.length - max) : next;
}

function pad(n: number): string {
  return n.toString().padStart(2, "0");
}
