import { Button, Flex, Switch, Text, TextField } from "@radix-ui/themes";
import { trpcClient, useTRPC } from "@renderer/trpc/client";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useEffect, useMemo, useState } from "react";
import type {
  NetworkRequest,
  NetworkSim,
} from "../../../../main/services/dev-network/schemas";

const MAX_DISPLAY = 400;

interface NetworkPanelProps {
  enabled: boolean;
}

export function NetworkPanel({ enabled }: NetworkPanelProps) {
  const trpcReact = useTRPC();
  const [requests, setRequests] = useState<NetworkRequest[]>([]);
  const [filter, setFilter] = useState("");
  const [sim, setSim] = useState<NetworkSim>({
    offline: false,
    slowDelayMs: 0,
  });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void trpcClient.dev.getNetworkRequests.query().then((snap) => {
      if (!cancelled) setRequests(snap.requests);
    });
    void trpcClient.dev.getNetworkSim.query().then((s) => {
      if (!cancelled) setSim(s);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  useSubscription(
    trpcReact.dev.onNetworkRequest.subscriptionOptions(undefined, {
      enabled,
      onData: (req) => {
        setRequests((prev) => {
          const next = [...prev, req];
          return next.length > MAX_DISPLAY
            ? next.slice(next.length - MAX_DISPLAY)
            : next;
        });
      },
    }),
  );

  useSubscription(
    trpcReact.dev.onNetworkSimChanged.subscriptionOptions(undefined, {
      enabled,
      onData: (s) => setSim(s),
    }),
  );

  const filtered = useMemo(() => {
    const lower = filter.trim().toLowerCase();
    const rows = lower
      ? requests.filter(
          (r) =>
            r.url.toLowerCase().includes(lower) ||
            r.host.toLowerCase().includes(lower) ||
            String(r.status ?? "").includes(lower),
        )
      : requests;
    return [...rows].reverse();
  }, [requests, filter]);

  const byHost = useMemo(() => {
    const map = new Map<
      string,
      { count: number; total: number; errors: number }
    >();
    for (const r of requests) {
      const cur = map.get(r.host) ?? { count: 0, total: 0, errors: 0 };
      cur.count += 1;
      cur.total += r.durationMs;
      if (!r.ok) cur.errors += 1;
      map.set(r.host, cur);
    }
    return [...map.entries()]
      .map(([host, v]) => ({ host, ...v, avg: v.total / v.count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
  }, [requests]);

  return (
    <Flex direction="column" gap="2" className="h-full overflow-hidden p-3">
      <Flex gap="2" align="center" wrap="wrap">
        <TextField.Root
          size="1"
          placeholder="Filter url, host, status..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="min-w-[180px] flex-1"
        />
        <Flex align="center" gap="1">
          <Switch
            size="1"
            checked={sim.offline}
            onCheckedChange={(checked) => {
              void trpcClient.dev.setNetworkSim.mutate({ offline: checked });
            }}
          />
          <Text size="1">Offline</Text>
        </Flex>
        <Flex align="center" gap="1">
          <Text size="1" color="gray">
            Delay
          </Text>
          <TextField.Root
            size="1"
            type="number"
            value={String(sim.slowDelayMs)}
            onChange={(e) => {
              const ms = Math.max(0, Number(e.target.value) || 0);
              void trpcClient.dev.setNetworkSim.mutate({ slowDelayMs: ms });
            }}
            style={{ width: 60 }}
          />
          <Text size="1" color="gray">
            ms
          </Text>
        </Flex>
        <Button
          size="1"
          variant="soft"
          onClick={async () => {
            await trpcClient.dev.clearNetworkRequests.mutate();
            setRequests([]);
          }}
        >
          Clear
        </Button>
        <Text size="1" color="gray" className="font-mono">
          {requests.length} captured
        </Text>
      </Flex>

      <Flex gap="4" className="overflow-hidden" flexGrow="1">
        <Flex direction="column" gap="1" className="w-1/2 overflow-y-auto">
          <Text size="1" weight="medium" color="gray">
            Recent
          </Text>
          <div className="grid grid-cols-[50px_50px_1fr_60px] gap-x-3 gap-y-0.5 font-mono text-[11px]">
            {filtered.map((r) => (
              <RequestRow key={r.id} req={r} />
            ))}
          </div>
        </Flex>

        <Flex direction="column" gap="1" className="w-1/2 overflow-y-auto">
          <Text size="1" weight="medium" color="gray">
            Top hosts
          </Text>
          <div className="grid grid-cols-[1fr_50px_60px_50px] gap-x-3 gap-y-0.5 font-mono text-[11px]">
            <Text size="1" color="gray" weight="medium">
              Host
            </Text>
            <Text size="1" color="gray" weight="medium">
              Count
            </Text>
            <Text size="1" color="gray" weight="medium">
              Avg
            </Text>
            <Text size="1" color="gray" weight="medium">
              Err
            </Text>
            {byHost.map((h) => (
              <HostRow key={h.host} {...h} />
            ))}
          </div>
        </Flex>
      </Flex>
    </Flex>
  );
}

function RequestRow({ req }: { req: NetworkRequest }) {
  const statusColor =
    req.status == null
      ? "red"
      : req.status >= 500
        ? "red"
        : req.status >= 400
          ? "amber"
          : undefined;
  const durColor =
    req.durationMs > 1000 ? "red" : req.durationMs > 300 ? "amber" : undefined;
  return (
    <>
      <Text size="1" color="gray">
        {req.method}
      </Text>
      <Text size="1" color={statusColor}>
        {req.status ?? "ERR"}
      </Text>
      <Text size="1" className="truncate" title={req.url}>
        {req.host || req.url}
      </Text>
      <Text size="1" color={durColor}>
        {req.durationMs.toFixed(0)}ms
      </Text>
    </>
  );
}

function HostRow({
  host,
  count,
  avg,
  errors,
}: {
  host: string;
  count: number;
  avg: number;
  errors: number;
}) {
  return (
    <>
      <Text size="1" className="truncate" title={host}>
        {host || "(unknown)"}
      </Text>
      <Text size="1">{count}</Text>
      <Text
        size="1"
        color={avg > 1000 ? "red" : avg > 300 ? "amber" : undefined}
      >
        {avg.toFixed(0)}ms
      </Text>
      <Text size="1" color={errors > 0 ? "red" : undefined}>
        {errors}
      </Text>
    </>
  );
}
