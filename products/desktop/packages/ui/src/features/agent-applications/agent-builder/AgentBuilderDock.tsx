import {
  ArrowRightIcon,
  NavigationArrowIcon,
  PlusIcon,
  SidebarSimpleIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
import type { AgentSpec } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  type CustomServerInput,
  useMcpConnect,
} from "@posthog/ui/features/mcp-server-manager/useMcpConnect";
import { Button } from "@posthog/ui/primitives/Button";
import { Flex, Text, Tooltip } from "@radix-ui/themes";
import { useEffect, useRef, useState } from "react";
import { useAuthStateValue } from "../../auth/store";
import { AgentChatPendingApprovalCard } from "../components/AgentChatPendingApprovalCard";
import { AgentChatSurface } from "../components/AgentChatSurface";
import { AgentDetailEmptyState } from "../components/AgentDetailLayout";
import { useAgentChat } from "../hooks/useAgentChat";
import { useAgentChatPendingApproval } from "../hooks/useAgentChatPendingApproval";
import { agentIngressBaseUrl } from "../utils/ingress";
import { AgentBuilderMcpConnectDialog } from "./AgentBuilderMcpConnectDialog";
import { AgentBuilderSecretForm } from "./AgentBuilderSecretForm";
import {
  AGENT_BUILDER_CHAT_ID,
  AGENT_BUILDER_SLUG,
  type AgentBuilderPageContext,
  useAgentBuilderStore,
} from "./agentBuilderStore";
import { suggestionsForPage } from "./agentBuilderSuggestions";
import {
  AGENT_BUILDER_CLIENT_TOOLS,
  useAgentBuilderClientTools,
} from "./useAgentBuilderClientTools";

const CHAT_ID = AGENT_BUILDER_CHAT_ID;

/** A rotating pool of composer placeholders — picked once per dock mount. */
const BUILDER_PLACEHOLDERS = [
  "Build me an agent that…",
  "What should we build today?",
  "Ask me to inspect, debug, or edit an agent…",
  "Describe an agent and I'll wire it up…",
  "Spin up a new agent, or fix an existing one…",
  "What's broken? Let's debug a session…",
  "Audit the fleet, tweak a prompt, ship an agent…",
  "Tell me what to change…",
];

/** The "what am I looking at" object sent to the agent builder (envelope + get_context). */
function buildAgentBuilderContext(
  page: AgentBuilderPageContext,
  followEnabled: boolean,
  project: { id: number | null; name: string | null; orgId: string | null },
): Record<string, unknown> {
  const agent = "slug" in page ? page.slug : undefined;
  const sessionId = page.kind === "agent-session" ? page.sessionId : undefined;
  const revisionId = page.kind === "agent-config" ? page.revision : undefined;
  return {
    page: page.kind,
    agent,
    session_id: sessionId,
    // The revision open in the configuration pane — the default target for
    // revision-scoped punch-outs (`set_secret`, `connect_mcp`).
    revision_id: revisionId,
    follow_enabled: followEnabled,
    // The project the user is currently in — the agent threads this into the
    // `project_id` arg of every `@posthog/*` tool (it's tenant-neutral and acts
    // on whatever project we report here).
    project_id: project.id ?? undefined,
    project_name: project.name ?? undefined,
    org_id: project.orgId ?? undefined,
    client: { kind: "posthog-code", version: "1" },
  };
}

/** Derive a unique, stable `mcps[].id` (tool-name prefix) from a label, avoiding
 *  collisions with existing entries. Mirrors the config pane's add-from-connection. */
function uniqueMcpId(label: string, mcps: unknown[]): string {
  const base =
    (label || "mcp")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 32) || "mcp";
  const taken = new Set(
    mcps.map((m) =>
      m && typeof m === "object"
        ? (m as Record<string, unknown>).id
        : undefined,
    ),
  );
  let id = base;
  for (let n = 2; taken.has(id); n++) id = `${base}-${n}`;
  return id;
}

/**
 * The Agent Builder chat — an always-on dock talking to the deployed meta-agent
 * (backend slug `agent-builder`). Streams through the shared
 * `useAgentChat`/`AgentChatSurface` stack, prepends the current `/code/agents`
 * page context to the first message, answers `get_context`, and lets the agent
 * drive the UI via `focus_*`.
 */
export function AgentBuilderDock() {
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  // The builder is a first-party, slug-routed agent reachable from any project,
  // so we address its ingress directly from (slug, region) rather than loading
  // its API record — which is project-scoped and 404s outside its home project.
  const ingressBaseUrl = agentIngressBaseUrl(AGENT_BUILDER_SLUG, cloudRegion);

  const client = useAuthenticatedClient();
  const currentProjectId = useAuthStateValue((s) => s.currentProjectId);
  const currentOrgId = useAuthStateValue((s) => s.currentOrgId);
  const orgProjectsMap = useAuthStateValue((s) => s.orgProjectsMap);
  const projectName =
    currentOrgId != null && currentProjectId != null
      ? (orgProjectsMap[currentOrgId]?.projects.find(
          (p) => p.id === currentProjectId,
        )?.name ?? null)
      : null;
  const page = useAgentBuilderStore((s) => s.page);
  const followMode = useAgentBuilderStore((s) => s.followMode);
  const setFollowMode = useAgentBuilderStore((s) => s.setFollowMode);
  const setVisible = useAgentBuilderStore((s) => s.setVisible);
  const seed = useAgentBuilderStore((s) => s.seed);
  const consumeSeed = useAgentBuilderStore((s) => s.consumeSeed);
  const pendingSecret = useAgentBuilderStore((s) => s.pendingSecret);
  const setPendingSecret = useAgentBuilderStore((s) => s.setPendingSecret);
  const pendingMcpConnect = useAgentBuilderStore((s) => s.pendingMcpConnect);
  const setPendingMcpConnect = useAgentBuilderStore(
    (s) => s.setPendingMcpConnect,
  );
  const lastSession = useAgentBuilderStore((s) => s.lastSession);
  const setLastSession = useAgentBuilderStore((s) => s.setLastSession);
  const { connectCustomAsync, refetchInstallations } = useMcpConnect();
  const [secretBusy, setSecretBusy] = useState(false);
  const [mcpConnectBusy, setMcpConnectBusy] = useState(false);
  const [placeholder] = useState(
    () =>
      BUILDER_PLACEHOLDERS[
        Math.floor(Math.random() * BUILDER_PLACEHOLDERS.length)
      ],
  );

  const clientTools = useAgentBuilderClientTools();
  const chat = useAgentChat({
    chatId: CHAT_ID,
    agentSlug: AGENT_BUILDER_SLUG,
    ingressBaseUrl,
    contextProvider: () =>
      buildAgentBuilderContext(page, followMode, {
        id: currentProjectId,
        name: projectName,
        orgId: currentOrgId,
      }),
    clientTools,
    supportedClientTools: AGENT_BUILDER_CLIENT_TOOLS,
  });
  const pendingApproval = useAgentChatPendingApproval(CHAT_ID);

  // Persist the session (with its project/org) as it's assigned, so a reload can
  // resume it in the right context.
  useEffect(() => {
    if (chat.sessionId) {
      setLastSession({
        id: chat.sessionId,
        projectId: currentProjectId,
        orgId: currentOrgId,
      });
    }
  }, [chat.sessionId, currentProjectId, currentOrgId, setLastSession]);

  // On (re)mount, rehydrate the last conversation from the ingress — the
  // in-memory chat store doesn't survive a reload. Fires once, after the
  // persisted `lastSession` has hydrated, and only when the chat is empty AND
  // the session belongs to the current project/org. `resume` re-attaches
  // `/listen` only if the session is still live; otherwise it's read-only
  // history to continue from.
  const resumedRef = useRef(false);
  useEffect(() => {
    if (resumedRef.current || !lastSession) return;
    if (chat.sessionId || chat.messages.length > 0) {
      resumedRef.current = true;
      return;
    }
    resumedRef.current = true;
    if (
      lastSession.projectId === currentProjectId &&
      lastSession.orgId === currentOrgId
    ) {
      void chat.resume(lastSession.id);
    }
  }, [lastSession, currentProjectId, currentOrgId, chat]);

  // Switching project/org starts the dock fresh — a conversation belongs to the
  // context it began in (the builder threads project_id into its tools; the
  // session is org-scoped at the ingress, so it isn't reachable from another
  // org). Skips the initial render so it doesn't wipe a just-resumed chat.
  const contextKeyRef = useRef<string | null>(null);
  useEffect(() => {
    const key = `${currentOrgId ?? ""}:${currentProjectId ?? ""}`;
    if (contextKeyRef.current === null) {
      contextKeyRef.current = key;
      return;
    }
    if (contextKeyRef.current === key) return;
    contextKeyRef.current = key;
    chat.newChat();
    setLastSession(null);
  }, [currentProjectId, currentOrgId, chat, setLastSession]);

  // Resolve a pending set_secret: PUT the value straight to the env-keys API
  // (never through the agent), then wake the parked session with the outcome.
  async function submitSecret(value: string) {
    if (!pendingSecret) return;
    setSecretBusy(true);
    try {
      await client.setAgentEnvKey(
        pendingSecret.agentSlug,
        pendingSecret.revisionId,
        pendingSecret.secret,
        value,
      );
      await chat.resolveInteractiveTool(pendingSecret.callId, {
        result: {
          key: pendingSecret.secret,
          action: pendingSecret.mode ?? "set",
        },
      });
      setPendingSecret(null);
    } catch (err) {
      await chat.resolveInteractiveTool(pendingSecret.callId, {
        error: err instanceof Error ? err.message : "set_secret_failed",
      });
      setPendingSecret(null);
    } finally {
      setSecretBusy(false);
    }
  }

  function cancelSecret() {
    if (!pendingSecret) return;
    void chat.resolveInteractiveTool(pendingSecret.callId, {
      error: "user_cancelled",
    });
    setPendingSecret(null);
  }

  // Resolve a pending connect_mcp: run the native connect (OAuth/api-key handoff
  // — tokens never reach the agent), then attach the resulting connection to the
  // target agent's draft spec and wake the parked session with the outcome.
  async function submitMcpConnect(values: CustomServerInput) {
    const pending = pendingMcpConnect;
    if (!pending) return;
    setMcpConnectBusy(true);
    try {
      const result = await connectCustomAsync(values);
      if (result && "error" in result && result.error) {
        throw new Error(result.error);
      }
      // The new install is keyed by url server-side ((team, user, url)); refetch
      // and match to recover its id (the OAuth callback doesn't return it).
      const installs = await refetchInstallations();
      const install = installs.find((i) => i.url === values.url);
      if (!install) {
        throw new Error("connection_not_found_after_connect");
      }
      // Attach to the target agent's spec: load → append an mcps[] entry that
      // references the connection → PATCH the (draft) revision.
      const rev = await client.getAgentRevision(
        pending.agentSlug,
        pending.revisionId,
      );
      if (!rev) {
        throw new Error("revision_not_found");
      }
      const spec = (rev.spec ?? {}) as AgentSpec;
      const mcps = Array.isArray(spec.mcps) ? [...spec.mcps] : [];
      const mcpId = uniqueMcpId(values.name || values.url, mcps);
      mcps.push({
        id: mcpId,
        url: values.url,
        connection: install.id,
        secrets: [],
      });
      await client.updateAgentRevisionSpec(
        pending.agentSlug,
        pending.revisionId,
        {
          ...spec,
          mcps,
        },
      );
      await chat.resolveInteractiveTool(pending.callId, {
        result: {
          connected: true,
          connection_id: install.id,
          mcp_id: mcpId,
          url: values.url,
        },
      });
      setPendingMcpConnect(null);
    } catch (err) {
      await chat.resolveInteractiveTool(pending.callId, {
        error: err instanceof Error ? err.message : "connect_mcp_failed",
      });
      setPendingMcpConnect(null);
    } finally {
      setMcpConnectBusy(false);
    }
  }

  function cancelMcpConnect() {
    if (!pendingMcpConnect) return;
    void chat.resolveInteractiveTool(pendingMcpConnect.callId, {
      error: "user_cancelled",
    });
    setPendingMcpConnect(null);
  }

  // Contextual hand-offs ("New agent" / "Edit with AI" / …): prefill the
  // seeded prompt into the composer when a new seed lands — never send it. The
  // user reviews and hits send, so opening the dock doesn't fire a chat on its
  // own. Prefilling is non-destructive, so no start-fresh-vs-continue prompt is
  // needed: it drops into whatever chat is open, and the header "New chat" (+)
  // clears first if the user wants a fresh conversation.
  const lastSeedRef = useRef(0);
  const [draft, setDraft] = useState<{ text: string; token: number } | null>(
    null,
  );
  useEffect(() => {
    if (!seed || seed.seq === lastSeedRef.current) return;
    lastSeedRef.current = seed.seq;
    consumeSeed(seed.seq);
    setDraft({ text: seed.prompt, token: seed.seq });
  }, [seed, consumeSeed]);

  return (
    <Flex
      direction="column"
      className="h-full min-h-0 border-(--amber-5) border-l-2 bg-(--amber-1)/30"
    >
      <Flex
        align="center"
        gap="2"
        className="shrink-0 border-(--amber-4) border-b bg-(--amber-2)/40 px-3 py-2"
      >
        <SparkleIcon size={15} weight="fill" className="text-(--accent-9)" />
        <Text className="font-medium text-[13px] text-gray-12">
          Agent Builder
        </Text>
        <Flex align="center" gap="2" className="ml-auto">
          <Tooltip
            content={
              followMode
                ? "Following — the agent builder can navigate your screen"
                : "Paused — the agent builder won't navigate"
            }
          >
            <Button
              variant={followMode ? "soft" : "ghost"}
              color={followMode ? undefined : "gray"}
              size="1"
              onClick={() => setFollowMode(!followMode)}
            >
              <NavigationArrowIcon
                size={13}
                weight={followMode ? "fill" : "regular"}
              />
            </Button>
          </Tooltip>
          <Tooltip content="New chat">
            <Button
              variant="ghost"
              color="gray"
              size="1"
              onClick={() => {
                setPendingSecret(null);
                setPendingMcpConnect(null);
                chat.newChat();
                setLastSession(null);
              }}
            >
              <PlusIcon size={14} />
            </Button>
          </Tooltip>
          <Tooltip content="Hide agent builder (⌘⇧I)">
            <Button
              variant="ghost"
              color="gray"
              size="1"
              onClick={() => setVisible(false)}
            >
              <SidebarSimpleIcon size={14} />
            </Button>
          </Tooltip>
        </Flex>
      </Flex>

      {!ingressBaseUrl ? (
        <div className="p-4">
          <AgentDetailEmptyState
            title="Agent Builder unavailable"
            description="Couldn't resolve your PostHog region, so the Agent Builder ingress can't be reached yet."
          />
        </div>
      ) : (
        <AgentChatSurface
          messages={chat.messages}
          isStreaming={chat.isStreaming}
          error={chat.error}
          scrollX={false}
          placeholder={placeholder}
          emptyState={<AgentBuilderEmptyState page={page} onPick={chat.send} />}
          emptyHint="Ask the agent builder to inspect, debug, or edit your agents. It can see what you're looking at and walk you there."
          draft={draft ?? undefined}
          belowConversation={
            pendingApproval ? (
              <AgentChatPendingApprovalCard
                idOrSlug={AGENT_BUILDER_SLUG}
                approval={pendingApproval}
                decide={chat.decideApproval}
              />
            ) : null
          }
          aboveComposer={
            pendingSecret ? (
              <AgentBuilderSecretForm
                pending={pendingSecret}
                busy={secretBusy}
                onSubmit={submitSecret}
                onCancel={cancelSecret}
              />
            ) : null
          }
          composerDisabledReason={
            pendingApproval ? "Waiting on your approval decision" : undefined
          }
          onSend={chat.send}
          onCancel={chat.cancel}
        />
      )}

      <AgentBuilderMcpConnectDialog
        pending={pendingMcpConnect}
        busy={mcpConnectBusy}
        onSubmit={submitMcpConnect}
        onCancel={cancelMcpConnect}
      />
    </Flex>
  );
}

/** Empty-dock state: a short prompt plus page-aware starter suggestions. */
function AgentBuilderEmptyState({
  page,
  onPick,
}: {
  page: AgentBuilderPageContext;
  onPick: (prompt: string) => void;
}) {
  const suggestions = suggestionsForPage(page);
  return (
    <Flex direction="column" className="h-full min-h-0 justify-end gap-3 p-3">
      <Text className="px-1 text-[12px] text-gray-10 leading-snug">
        Ask the agent builder to inspect, debug, or edit your agents — it can
        see what you're looking at and walk you there. Try:
      </Text>
      <Flex direction="column" className="gap-2.5">
        {suggestions.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => onPick(s.prompt)}
            className="group flex items-center gap-2 rounded-(--radius-3) border border-(--gray-5) bg-(--gray-2) px-3 py-2 text-left transition-colors hover:border-(--gray-7) hover:bg-(--gray-3)"
          >
            <SparkleIcon
              size={13}
              weight="fill"
              className="shrink-0 text-(--accent-9)"
            />
            <span className="min-w-0 flex-1 truncate text-[12.5px] text-gray-12">
              {s.label}
            </span>
            <ArrowRightIcon
              size={12}
              className="shrink-0 text-gray-8 transition-colors group-hover:text-gray-11"
            />
          </button>
        ))}
      </Flex>
    </Flex>
  );
}
