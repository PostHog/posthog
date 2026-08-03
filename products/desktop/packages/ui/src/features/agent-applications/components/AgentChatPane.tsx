import {
  ChatCircleIcon,
  InfoIcon,
  PlusIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import type { CloudRegion } from "@posthog/shared";
import { Button } from "@posthog/ui/primitives/Button";
import { Flex, Text } from "@radix-ui/themes";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAuthStateValue } from "../../auth/store";
import {
  type ChatHistoryEntry,
  useChatHistoryStore,
} from "../chat/chatHistoryStore";
import { useAgentApplication } from "../hooks/useAgentApplication";
import { useAgentChat } from "../hooks/useAgentChat";
import { useAgentChatPendingApproval } from "../hooks/useAgentChatPendingApproval";
import { useAgentRevision } from "../hooks/useAgentRevision";
import { resolveIngressBaseUrl } from "../utils/ingress";
import { AgentChatPendingApprovalCard } from "./AgentChatPendingApprovalCard";
import { AgentChatSurface } from "./AgentChatSurface";
import { AgentDetailEmptyState, AgentDetailLayout } from "./AgentDetailLayout";

const EMPTY_CHATS: ChatHistoryEntry[] = [];

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

/** Compact "x ago" for the rail, from an epoch-ms timestamp. */
function relativeTime(ms: number): string {
  const diff = Date.now() - ms;
  const s = Math.floor(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/**
 * In-app chat against a deployed agent. Streams the agent-ingress SSE through
 * the native `ConversationView`. Only meaningful for agents that expose a chat
 * trigger and have a public ingress URL.
 *
 * A left rail lists the chats the user started *here* (persisted locally —
 * never the agent's full server session list, which can include real customer
 * chats), and a banner makes clear which revision this targets.
 *
 * When `revisionId` targets a non-live revision (the "Test draft" affordance
 * from the revision bar), the hook mints a short-lived ingress JWT and routes
 * the run to that draft; chatId/banner switch accordingly so a draft session
 * can't be confused with a live one. Side effects (Slack, approvals, tools)
 * still run for real — only the revision serving the request differs.
 */
export function AgentChatPane({
  idOrSlug,
  revisionId,
  resumeSessionId,
}: {
  idOrSlug: string;
  revisionId?: string | null;
  /**
   * Optional session id from the route (`?session=`); when set, the pane
   * re-attaches to that session on first mount. Lets rail clicks that cross
   * revisions land on the right surface AND immediately resume — without it,
   * the new mount would render an empty composer.
   */
  resumeSessionId?: string | null;
}) {
  const navigate = useNavigate();
  const { data: application } = useAgentApplication(idOrSlug);
  // null/equal-to-live → fall back to the live revision; explicit non-live
  // revision id → route this chat to the draft.
  const targetRevisionId =
    revisionId && revisionId !== application?.live_revision
      ? revisionId
      : (application?.live_revision ?? null);
  const isDraftRevisionChat =
    !!revisionId && revisionId !== application?.live_revision;
  const { data: revision } = useAgentRevision(idOrSlug, targetRevisionId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const ingressBaseUrl = resolveIngressBaseUrl(
    application?.ingress_base_url,
    cloudRegion,
  );
  const hasChatTrigger = (revision?.spec?.triggers ?? []).some(
    (t) => rec(t).type === "chat",
  );
  // Keyed by revision so a draft chat and the live chat coexist in the store
  // without trampling each other.
  const chatId = isDraftRevisionChat
    ? `preview:${idOrSlug}:${revisionId}`
    : `preview:${idOrSlug}`;
  const chat = useAgentChat({
    chatId,
    agentSlug: idOrSlug,
    ingressBaseUrl,
    revisionId: isDraftRevisionChat ? revisionId : null,
    recordHistory: true,
  });
  const pendingApproval = useAgentChatPendingApproval(chatId);
  const chats = useChatHistoryStore((s) => s.byAgent[idOrSlug]) ?? EMPTY_CHATS;
  const removeChat = useChatHistoryStore((s) => s.remove);

  // Partition the rail into "matches the current target" vs everything else
  // so a live view doesn't drown in old draft chats (and vice-versa). The
  // expander reveals the rest on demand.
  const currentRev = isDraftRevisionChat ? (revisionId ?? null) : null;
  const { matchingChats, otherChats } = useMemo(() => {
    const matching: ChatHistoryEntry[] = [];
    const other: ChatHistoryEntry[] = [];
    for (const c of chats) {
      if ((c.revisionId ?? null) === currentRev) matching.push(c);
      else other.push(c);
    }
    return { matchingChats: matching, otherChats: other };
  }, [chats, currentRev]);
  const [showOthers, setShowOthers] = useState(false);
  // Reset the expander whenever the target switches so each surface starts
  // focused on its own chats.
  const lastRevRef = useRef(currentRev);
  if (lastRevRef.current !== currentRev) {
    lastRevRef.current = currentRev;
    if (showOthers) setShowOthers(false);
  }

  // Auto-resume the URL-named session exactly once per param value. Tracked by
  // a ref so a re-render or chat.resume identity change can't re-fire on the
  // same id. After kicking it off we clear the URL hint so an in-pane "New
  // chat" can't be silently undone by a refresh.
  const resumedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!resumeSessionId || resumedRef.current === resumeSessionId) return;
    resumedRef.current = resumeSessionId;
    chat.resume(resumeSessionId);
    // Anchored to this route so TanStack can resolve the search-fn against the
    // chat route's typed shape (the no-`to` form widens to `never`).
    navigate({
      to: "/code/agents/applications/$idOrSlug/chat",
      params: { idOrSlug },
      search: (prev) => ({ ...prev, session: undefined }),
    });
  }, [resumeSessionId, chat.resume, navigate, idOrSlug]);

  // The rail mixes chats from every revision; decide per click whether to
  // resume inline (same target) or navigate to a different revision's surface.
  const handleRailSelect = (entry: ChatHistoryEntry) => {
    if ((entry.revisionId ?? null) === currentRev) {
      chat.resume(entry.sessionId);
      return;
    }
    navigate({
      to: "/code/agents/applications/$idOrSlug/chat",
      params: { idOrSlug },
      search: entry.revisionId
        ? { revision: entry.revisionId, session: entry.sessionId }
        : { session: entry.sessionId },
    });
  };

  return (
    <AgentDetailLayout idOrSlug={idOrSlug} activeTab="chat" fill>
      {!ingressBaseUrl ? (
        <div className="p-6">
          <AgentDetailEmptyState
            title="No ingress URL"
            description="This deployment has no public ingress URL, so the agent can't be reached for a live chat."
          />
        </div>
      ) : !hasChatTrigger ? (
        <div className="p-6">
          <AgentDetailEmptyState
            title="No chat trigger"
            description={
              isDraftRevisionChat
                ? "This draft revision doesn't expose a chat trigger, so there's nothing to chat with. Add a chat trigger via the agent builder to test it here."
                : "This agent's live revision doesn't expose a chat trigger, so there's nothing to chat with. Add a chat trigger via the agent builder to test it here."
            }
          />
        </div>
      ) : (
        <Flex className="h-full min-h-0">
          <ChatHistoryRail
            chats={matchingChats}
            otherChats={otherChats}
            showOthers={showOthers}
            onToggleShowOthers={() => setShowOthers((v) => !v)}
            activeSessionId={chat.sessionId}
            onNewChat={chat.newChat}
            onSelect={handleRailSelect}
            onDelete={(sessionId) => removeChat(idOrSlug, sessionId)}
          />
          <Flex direction="column" className="min-w-0 flex-1">
            <RevisionChatBanner
              revisionId={targetRevisionId}
              isDraft={isDraftRevisionChat}
              model={revision?.spec?.model}
              region={cloudRegion}
            />
            <AgentChatSurface
              messages={chat.messages}
              isStreaming={chat.isStreaming}
              error={chat.error}
              emptyHint="Send a message to start a session and test this agent live."
              belowConversation={
                pendingApproval ? (
                  <AgentChatPendingApprovalCard
                    idOrSlug={idOrSlug}
                    approval={pendingApproval}
                    decide={chat.decideApproval}
                  />
                ) : null
              }
              composerDisabledReason={
                pendingApproval
                  ? "Waiting on your approval decision"
                  : undefined
              }
              onSend={chat.send}
              onCancel={chat.cancel}
            />
          </Flex>
        </Flex>
      )}
    </AgentDetailLayout>
  );
}

function RevisionChatBanner({
  revisionId,
  isDraft,
  model,
  region,
}: {
  revisionId: string | null;
  isDraft: boolean;
  model: string | undefined;
  region: CloudRegion | null;
}) {
  return (
    <Flex
      align="center"
      gap="2"
      className={`shrink-0 border-(--gray-5) border-b px-4 py-2 ${
        isDraft ? "bg-(--amber-2)" : "bg-(--gray-2)"
      }`}
    >
      <InfoIcon size={14} className="shrink-0 text-gray-10" />
      <Text className="text-[12px] text-gray-11 leading-snug">
        {isDraft
          ? "Chatting with a draft revision — Slack posts, approvals, and tools all run for real. Promote the revision to make this the live one."
          : "Chatting with the live revision — messages run against the currently deployed revision. Only chats you start here appear in the list."}
      </Text>
      <Flex align="center" gap="2" className="ml-auto shrink-0">
        {model ? (
          <Text className="text-[11px] text-gray-10">{model}</Text>
        ) : null}
        {revisionId ? (
          <Text
            className="font-mono text-[11px] text-gray-10"
            title={revisionId}
          >
            rev {revisionId.slice(0, 8)}
          </Text>
        ) : null}
        {region ? (
          <Text className="text-[11px] text-gray-10 uppercase">{region}</Text>
        ) : null}
      </Flex>
    </Flex>
  );
}

function ChatHistoryRail({
  chats,
  otherChats,
  showOthers,
  onToggleShowOthers,
  activeSessionId,
  onNewChat,
  onSelect,
  onDelete,
}: {
  chats: ChatHistoryEntry[];
  /** Chats from other revisions — hidden behind an expander to keep this surface focused. */
  otherChats: ChatHistoryEntry[];
  showOthers: boolean;
  onToggleShowOthers: () => void;
  activeSessionId: string | null;
  onNewChat: () => void;
  /** Receives the full entry so the parent can route by revision, not just resume. */
  onSelect: (entry: ChatHistoryEntry) => void;
  onDelete: (sessionId: string) => void;
}) {
  return (
    <Flex
      direction="column"
      className="w-56 shrink-0 border-(--gray-5) border-r"
    >
      <div className="shrink-0 p-2">
        <Button
          variant="soft"
          color="gray"
          size="1"
          className="w-full justify-start"
          onClick={onNewChat}
        >
          <PlusIcon size={13} />
          New chat
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-2 pb-2">
        {chats.length === 0 && (otherChats.length === 0 || !showOthers) ? (
          <Text className="block px-1 py-2 text-[11.5px] text-gray-9 leading-snug">
            Chats you start here will show up in this list.
          </Text>
        ) : (
          <Flex direction="column" gap="1">
            {chats.map((c) => (
              <RailEntry
                key={c.sessionId}
                entry={c}
                active={c.sessionId === activeSessionId}
                onSelect={onSelect}
                onDelete={onDelete}
              />
            ))}
            {otherChats.length > 0 ? (
              <>
                <button
                  type="button"
                  onClick={onToggleShowOthers}
                  className="mt-1 block rounded-(--radius-2) px-2 py-1 text-left text-[10.5px] text-gray-10 uppercase tracking-wide hover:bg-(--gray-3) hover:text-gray-12"
                >
                  {showOthers
                    ? "Hide other revisions"
                    : `Show ${otherChats.length} from other revision${otherChats.length === 1 ? "" : "s"}`}
                </button>
                {showOthers
                  ? otherChats.map((c) => (
                      <RailEntry
                        key={c.sessionId}
                        entry={c}
                        active={c.sessionId === activeSessionId}
                        onSelect={onSelect}
                        onDelete={onDelete}
                      />
                    ))
                  : null}
              </>
            ) : null}
          </Flex>
        )}
      </div>
    </Flex>
  );
}

function RailEntry({
  entry,
  active,
  onSelect,
  onDelete,
}: {
  entry: ChatHistoryEntry;
  active: boolean;
  onSelect: (entry: ChatHistoryEntry) => void;
  onDelete: (sessionId: string) => void;
}) {
  return (
    <div className="group relative">
      <button
        type="button"
        onClick={() => onSelect(entry)}
        className={`flex w-full items-start gap-2 rounded-(--radius-2) py-1.5 pr-7 pl-2 text-left ${
          active ? "bg-(--accent-3)" : "hover:bg-(--gray-3)"
        }`}
      >
        <ChatCircleIcon size={13} className="mt-0.5 shrink-0 text-gray-10" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12px] text-gray-12 leading-tight">
            {entry.title || "Untitled chat"}
          </span>
          <Flex align="center" gap="1" className="text-[10.5px] text-gray-9">
            <span>{relativeTime(entry.startedAt)}</span>
            {entry.revisionId ? (
              <>
                <span aria-hidden>·</span>
                <span
                  className="rounded-(--radius-1) bg-(--amber-3) px-1 font-mono text-(--amber-11) text-[10px]"
                  title={`Chat against draft revision ${entry.revisionId}`}
                >
                  rev {entry.revisionId.slice(0, 8)}
                </span>
              </>
            ) : null}
          </Flex>
        </span>
      </button>
      <button
        type="button"
        aria-label="Remove chat"
        onClick={() => onDelete(entry.sessionId)}
        className="absolute top-1.5 right-1 rounded p-0.5 text-gray-9 opacity-0 hover:text-gray-12 group-hover:opacity-100"
      >
        <TrashIcon size={12} />
      </button>
    </div>
  );
}
