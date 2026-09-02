import { Clock, Gauge } from "@phosphor-icons/react";
import type { AutoresearchRun } from "@posthog/core/autoresearch/schemas";
import { getAutoresearchElapsedMs } from "@posthog/core/autoresearch/stats";
import type { ContextUsage } from "@posthog/core/sessions/contextUsage";
import { Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";
import { formatDuration } from "../sessions/components/GeneratingIndicator";
import { formatTokensCompact } from "../sessions/contextColors";

export function AutoresearchRuntimeStats({
  run,
  usage,
}: {
  run: AutoresearchRun;
  usage: ContextUsage | null;
}) {
  const elapsed = useRunElapsed(run);
  const contextValue = usage
    ? usage.size > 0
      ? `${formatTokensCompact(usage.used)} / ${formatTokensCompact(usage.size)}`
      : formatTokensCompact(usage.used)
    : "Waiting";
  const contextDetail = usage
    ? usage.size > 0
      ? `${usage.percentage}% of current window`
      : "Current context"
    : "No usage update yet";
  return (
    <section
      className="grid @min-[520px]:grid-cols-2 grid-cols-1 gap-2"
      aria-label="Autoresearch runtime metrics"
    >
      <RuntimeMetric
        icon={<Clock size={15} />}
        label="This run's active time"
        value={formatDuration(elapsed, 0)}
        detail={runtimeDetail(run)}
      />
      <RuntimeMetric
        icon={<Gauge size={15} />}
        label="Context tokens"
        value={contextValue}
        detail={contextDetail}
      />
    </section>
  );
}

function RuntimeMetric({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-md border border-gray-5 bg-gray-1 px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-gray-10">
        {icon}
        <Text size="1">{label}</Text>
      </div>
      <Text as="div" size="3" weight="medium" className="mt-1 tabular-nums">
        {value}
      </Text>
      <Text as="div" size="1" color="gray" className="mt-0.5">
        {detail}
      </Text>
    </div>
  );
}

function useRunElapsed(run: AutoresearchRun): number {
  const [now, setNow] = useState(() => Date.now());
  const live = run.endedAt === null && run.status === "running";

  useEffect(() => {
    if (!live) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [live]);

  return getAutoresearchElapsedMs(run, now);
}

function runtimeDetail(run: AutoresearchRun): string {
  if (run.status === "paused") return "Paused · this run only";
  if (run.status === "interrupted") return "Reconnecting · active time paused";
  if (run.endedAt !== null) return "Final duration for this run";
  return "This run only · excludes pauses";
}
