import { Button, Flex, Text } from "@radix-ui/themes";
import { trpcClient, useTRPC } from "@renderer/trpc/client";
import { useQuery } from "@tanstack/react-query";
import { Activity, Clock, FileQuestion } from "lucide-react";
import { useEffect, useState } from "react";

interface AgentsPanelProps {
  enabled: boolean;
}

const REFRESH_INTERVAL_MS = 1000;

export function AgentsPanel({ enabled }: AgentsPanelProps) {
  const trpcReact = useTRPC();
  const { data, refetch } = useQuery({
    ...trpcReact.dev.getAgentsSnapshot.queryOptions(),
    enabled,
    refetchInterval: enabled ? REFRESH_INTERVAL_MS : false,
  });

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const sessions = data?.sessions ?? [];
  const pending = data?.pendingPermissions ?? [];

  return (
    <Flex direction="column" gap="3" className="h-full overflow-y-auto p-3">
      <Flex gap="2" align="center">
        <Text size="1" color="gray" className="font-mono">
          {sessions.length} session{sessions.length === 1 ? "" : "s"}
        </Text>
        <Text size="1" color="gray">
          ·
        </Text>
        <Text size="1" color="gray" className="font-mono">
          {pending.length} pending permission{pending.length === 1 ? "" : "s"}
        </Text>
        <Button size="1" variant="soft" onClick={() => void refetch()}>
          Refresh
        </Button>
      </Flex>

      {sessions.length === 0 && pending.length === 0 && (
        <Text size="1" color="gray">
          No active agent sessions.
        </Text>
      )}

      {sessions.length > 0 && (
        <Flex direction="column" gap="1">
          <Text size="1" weight="medium" color="gray">
            Active sessions
          </Text>
          <div className="overflow-hidden rounded-md border border-(--gray-5) bg-(--gray-1)">
            <div className="grid grid-cols-[1fr_90px_70px_80px_80px] gap-x-3 border-(--gray-5) border-b bg-(--gray-2) px-3 py-1.5 font-mono text-(--gray-10) text-[10px] uppercase tracking-wide">
              <span>Task</span>
              <span>Adapter</span>
              <span>State</span>
              <span>Activity</span>
              <span>Idle in</span>
            </div>
            <div className="divide-y divide-(--gray-4)">
              {sessions.map((s) => (
                <SessionRow key={s.taskRunId} session={s} now={now} />
              ))}
            </div>
          </div>
        </Flex>
      )}

      {pending.length > 0 && (
        <Flex direction="column" gap="1">
          <Text size="1" weight="medium" color="gray">
            Pending permissions
          </Text>
          <div className="overflow-hidden rounded-md border border-(--amber-6) bg-(--amber-2)">
            {pending.map((p) => (
              <div
                key={`${p.taskRunId}:${p.toolCallId}`}
                className="flex items-center gap-2 px-3 py-1.5 font-mono text-[11px]"
              >
                <FileQuestion
                  size={12}
                  className="shrink-0 text-(--amber-11)"
                />
                <Text size="1" className="truncate text-(--gray-12)">
                  task={p.taskRunId.slice(0, 8)}… toolCall={p.toolCallId}
                </Text>
                <Button
                  size="1"
                  variant="soft"
                  color="red"
                  onClick={() => {
                    void trpcClient.agent.cancelPermission.mutate({
                      taskRunId: p.taskRunId,
                      toolCallId: p.toolCallId,
                    });
                  }}
                >
                  Cancel
                </Button>
              </div>
            ))}
          </div>
        </Flex>
      )}
    </Flex>
  );
}

interface DevSession {
  taskRunId: string;
  taskId: string;
  repoPath: string;
  adapter: string;
  model: string | null;
  sessionId: string | null;
  channel: string;
  createdAt: number;
  lastActivityAt: number;
  promptPending: boolean;
  inFlightToolCalls: number;
  idleDeadline: number | null;
}

function SessionRow({ session, now }: { session: DevSession; now: number }) {
  const ageMs = now - session.lastActivityAt;
  const idleIn = session.idleDeadline ? session.idleDeadline - now : null;
  return (
    <div className="grid grid-cols-[1fr_90px_70px_80px_80px] items-center gap-x-3 px-3 py-1 font-mono text-[11px]">
      <Flex direction="column" className="min-w-0">
        <Text size="1" className="truncate text-(--gray-12)">
          {session.taskId.slice(0, 12)}
        </Text>
        <Text size="1" color="gray" className="truncate text-[10px]">
          {session.model ?? "default"}
        </Text>
      </Flex>
      <Text size="1" color="gray">
        {session.adapter}
      </Text>
      <Flex align="center" gap="1">
        {session.promptPending ? (
          <>
            <Activity size={10} className="text-(--green-11)" />
            <Text size="1" className="text-(--green-11)">
              busy
            </Text>
          </>
        ) : session.inFlightToolCalls > 0 ? (
          <Text size="1" className="text-(--amber-11)">
            tool×{session.inFlightToolCalls}
          </Text>
        ) : (
          <Text size="1" color="gray">
            idle
          </Text>
        )}
      </Flex>
      <Flex align="center" gap="1">
        <Clock size={10} className="text-(--gray-10)" />
        <Text size="1" color="gray">
          {formatDuration(ageMs)}
        </Text>
      </Flex>
      <Text
        size="1"
        color={idleIn != null && idleIn < 60_000 ? "amber" : undefined}
      >
        {idleIn != null ? formatDuration(idleIn) : "—"}
      </Text>
    </div>
  );
}

function formatDuration(ms: number): string {
  if (ms < 0) return "now";
  if (ms < 1000) return "now";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h`;
}
