import type { AgentApplicationSessionDetail } from "@posthog/shared/agent-platform-types";
import { ThreadView } from "@posthog/ui/features/sessions/components/ThreadView";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Flex, Text } from "@radix-ui/themes";
import { type ReactNode, useMemo, useState } from "react";
import { conversationToAcpMessages } from "../chat/conversationToAcp";
import { useAgentApplicationSession } from "../hooks/useAgentApplicationSession";
import {
  formatDuration,
  formatSpendUsd,
  sessionStateColor,
} from "../utils/format";
import { RefreshIndicator } from "./RefreshIndicator";
import { SessionLogsView } from "./SessionLogsView";

type DetailTab = "conversation" | "logs";

interface SessionMetrics {
  messages: number;
  toolCalls: number;
  errors: number;
  /** Distinct models that answered, in first-seen order. Usually one; more than
   *  one means the turn(s) fell back across the policy list. */
  models: string[];
}

function computeMetrics(
  session: AgentApplicationSessionDetail,
): SessionMetrics {
  let toolCalls = 0;
  let errors = 0;
  const models: string[] = [];
  const seenModels = new Set<string>();
  for (const msg of session.conversation) {
    if (msg.role === "assistant") {
      for (const part of msg.content) {
        if (part.type === "toolCall") toolCalls += 1;
      }
      if (msg.errorMessage) errors += 1;
      if (msg.model && !seenModels.has(msg.model)) {
        seenModels.add(msg.model);
        models.push(msg.model);
      }
    } else if (msg.role === "toolResult" && msg.isError) {
      errors += 1;
    }
  }
  return {
    messages: session.conversation_total_turns ?? session.conversation.length,
    toolCalls,
    errors,
    models,
  };
}

/** Reads a cron "fired by" descriptor off trigger_metadata, if present. */
function cronFiredBy(
  meta: AgentApplicationSessionDetail["trigger_metadata"],
): { cronName: string; schedule?: string } | null {
  if (!meta || typeof meta !== "object") return null;
  if ((meta as { kind?: unknown }).kind !== "cron") return null;
  const cronName = (meta as { cron_name?: unknown }).cron_name;
  if (typeof cronName !== "string") return null;
  const schedule = (meta as { schedule?: unknown }).schedule;
  return {
    cronName,
    schedule: typeof schedule === "string" ? schedule : undefined,
  };
}

/**
 * The session detail body: state/cron badges + KPI strip + a refresh control,
 * with Conversation (read-only, through code's native `ConversationView`) and
 * structured Logs tabs. Reused by the full-screen session route and embedded in
 * the approval detail's Session tab. Owns no page chrome (no back link/title).
 */
export function AgentSessionDetailBody({
  idOrSlug,
  sessionId,
  showStateBadge = true,
}: {
  idOrSlug: string;
  sessionId: string;
  /** Hide the state badge when the host already shows it (full-screen header). */
  showStateBadge?: boolean;
}) {
  const {
    data: session,
    isLoading,
    isError,
    isFetching,
    dataUpdatedAt,
    refetch,
  } = useAgentApplicationSession(idOrSlug, sessionId);
  const [tab, setTab] = useState<DetailTab>("conversation");

  const events = useMemo(
    () => (session ? conversationToAcpMessages(session.conversation) : []),
    [session],
  );
  const metrics = useMemo(
    () => (session ? computeMetrics(session) : null),
    [session],
  );
  const firedBy = session ? cronFiredBy(session.trigger_metadata) : null;

  return (
    <Flex direction="column" className="h-full min-h-0">
      <Flex
        direction="column"
        gap="3"
        className="shrink-0 cursor-default select-none border-(--gray-5) border-b px-6 pt-4"
      >
        {(showStateBadge && session) ||
        firedBy ||
        session?.conversation_trimmed ? (
          <Flex align="center" gap="2" wrap="wrap">
            {showStateBadge && session ? (
              <Badge color={sessionStateColor(session.state)}>
                {session.state}
              </Badge>
            ) : null}
            {firedBy ? (
              <Badge color="gray" title={firedBy.schedule}>
                cron · {firedBy.cronName}
              </Badge>
            ) : null}
            {session?.conversation_trimmed ? (
              <Badge color="gray">
                showing last {session.conversation.length} of{" "}
                {session.conversation_total_turns ??
                  session.conversation.length}
              </Badge>
            ) : null}
          </Flex>
        ) : null}

        <Flex align="center" justify="between" gap="3">
          <Flex gap="5" wrap="wrap" className="min-w-0">
            {session && metrics ? (
              <>
                <MetricItem label="Messages" value={String(metrics.messages)} />
                <MetricItem
                  label="Tool calls"
                  value={String(metrics.toolCalls)}
                />
                {metrics.models.length > 0 ? (
                  <MetricItem
                    label="Model"
                    value={
                      metrics.models.length === 1
                        ? metrics.models[0]
                        : `${metrics.models[0]} +${metrics.models.length - 1}`
                    }
                    title={metrics.models.join(", ")}
                    mono
                  />
                ) : null}
                <MetricItem
                  label="Cost"
                  value={formatSpendUsd(session.usage_total.cost_total)}
                />
                <MetricItem
                  label="Duration"
                  value={formatDuration(session.created_at, session.updated_at)}
                />
                <MetricItem
                  label="Errors"
                  value={String(metrics.errors)}
                  tone={metrics.errors > 0 ? "bad" : undefined}
                />
              </>
            ) : null}
          </Flex>
          <RefreshIndicator
            updatedAt={dataUpdatedAt}
            isFetching={isFetching}
            onRefresh={() => void refetch()}
          />
        </Flex>

        <Flex gap="1" className="-mb-px">
          {(["conversation", "logs"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`border-b-2 px-3 pb-2.5 text-[12.5px] capitalize ${
                t === tab
                  ? "border-(--accent-9) font-medium text-gray-12"
                  : "border-transparent text-gray-11 hover:text-gray-12"
              }`}
            >
              {t}
            </button>
          ))}
        </Flex>
      </Flex>

      {/* Flex column with a definite height: ConversationView's root is
          `relative flex-1` with an absolutely-positioned VirtualizedList, so it
          only gets height inside a flex column (matches prod SessionView). */}
      <div className="flex min-h-0 flex-1 flex-col">
        {isLoading ? (
          <Centered>
            <div className="h-24 w-full max-w-2xl animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)" />
          </Centered>
        ) : isError || !session ? (
          <Centered>
            <EmptyState
              title="Couldn't load this session"
              description="It may have been purged, or the agent platform API returned an error."
            />
          </Centered>
        ) : tab === "logs" ? (
          // ConversationView owns its own scroll; the logs list does not.
          <div className="h-full overflow-auto">
            <SessionLogsView
              idOrSlug={idOrSlug}
              sessionId={sessionId}
              startIso={session.created_at}
              enabled={tab === "logs"}
            />
          </div>
        ) : session.conversation.length === 0 ? (
          <Centered>
            <EmptyState
              title="No messages yet"
              description="This session hasn't produced any conversation turns."
            />
          </Centered>
        ) : (
          <ThreadView events={events} isPromptPending={null} />
        )}
      </div>
    </Flex>
  );
}

function MetricItem({
  label,
  value,
  tone,
  mono,
  title,
}: {
  label: string;
  value: string;
  tone?: "bad";
  mono?: boolean;
  title?: string;
}) {
  return (
    <Flex direction="column" gap="0.5">
      <Text className="text-[10px] text-gray-10 uppercase tracking-wide">
        {label}
      </Text>
      <Text
        title={title}
        className={`font-semibold leading-none ${
          mono ? "text-[12.5px] [font-family:var(--font-mono)]" : "text-[14px]"
        } ${tone === "bad" ? "text-(--red-11)" : "text-gray-12"}`}
      >
        {value}
      </Text>
    </Flex>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center px-6 py-10">
      {children}
    </div>
  );
}

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: ReactNode;
}) {
  return (
    <Flex
      direction="column"
      align="center"
      gap="1"
      className="rounded-(--radius-2) border border-(--gray-5) border-dashed px-6 py-10 text-center"
    >
      <Text className="font-medium text-[13px] text-gray-12">{title}</Text>
      <Text className="max-w-md text-[12px] text-gray-11 leading-snug">
        {description}
      </Text>
    </Flex>
  );
}
