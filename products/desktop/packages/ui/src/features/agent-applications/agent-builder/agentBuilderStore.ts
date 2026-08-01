import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/** The deployed meta-agent the agent builder dock always talks to. */
export const AGENT_BUILDER_SLUG = "agent-builder";

/** Key for the agent builder's chat in the core `agentChatStore`. */
export const AGENT_BUILDER_CHAT_ID = "agent-builder";

/**
 * What the user is currently looking at in `/code/agents`. Mirrors the console's
 * `AgentBuilderPageContext` so the agent builder can resolve deictic references ("this
 * agent", "this session") and drive the right `focus_*` target. Each route
 * registers its context on mount via `useSetAgentBuilderPage`.
 */
export type AgentBuilderPageContext =
  | { kind: "agent-list" }
  | { kind: "scouts" }
  | { kind: "agent"; slug: string }
  | { kind: "agent-config"; slug: string; node?: string; revision?: string }
  | { kind: "agent-sessions"; slug: string }
  | { kind: "agent-session"; slug: string; sessionId: string }
  | { kind: "agent-approvals"; slug: string; request?: string }
  | { kind: "agent-memory"; slug: string }
  | { kind: "agent-observability"; slug: string }
  | { kind: "agent-chat"; slug: string }
  | { kind: "unknown" };

/** A pending contextual hand-off: open the dock and prefill the composer with
 *  `prompt` (the user reviews and sends — it is never auto-sent). */
export interface AgentBuilderSeed {
  /** Monotonic id so a consumer can mark exactly one seed handled. */
  seq: number;
  prompt: string;
  /** Agent the seed is about, for the context envelope. */
  agentSlug: string | null;
}

/**
 * An in-flight `set_secret` punch-out. The agent parked its turn; the dock
 * renders a form for these, and on submit PUTs the key + wakes the session.
 */
export interface PendingSecret {
  /** The parked tool call to resolve via `/send`. */
  callId: string;
  agentSlug: string;
  /**
   * Revision the secret is written to. Env keys are revision-scoped, so the
   * `set_secret` punch-out must target a specific revision (the one the agent
   * is editing). Sourced from the tool args, falling back to the dock's
   * current `agent-config` page context.
   */
  revisionId: string;
  /** Env key name, e.g. "ANTHROPIC_KEY". The value is never seen by the agent. */
  secret: string;
  mode?: "set" | "rotate";
  purpose?: string;
}

/**
 * An in-flight `connect_mcp` punch-out. The agent parked its turn; the dock
 * renders a prefilled connect form, the user completes the auth (OAuth / api
 * key — tokens never reach the agent), and on success the new connection is
 * written into the target agent's spec and the session woken.
 */
export interface PendingMcpConnect {
  /** The parked tool call to resolve via `/send`. */
  callId: string;
  /** Agent whose spec gets the `mcps[].connection` entry. */
  agentSlug: string;
  /** Draft revision the mcps[] entry is written to (spec edits are revision
   *  scoped). Sourced from the tool args, falling back to the dock's current
   *  `agent-config` page context. */
  revisionId: string;
  /** Prefilled server name (editable by the user). */
  name?: string;
  /** Prefilled MCP server URL (editable by the user). */
  url?: string;
  /** One-line reason shown above the form. */
  purpose?: string;
}

interface AgentBuilderStore {
  /** Dock open/closed (persisted). */
  visible: boolean;
  /** Whether the agent's `focus_*` tools may navigate the UI (persisted). */
  followMode: boolean;
  /** Current page context (ephemeral — re-registered per route). */
  page: AgentBuilderPageContext;
  /** Pending edit-with-AI hand-off (ephemeral). */
  seed: AgentBuilderSeed | null;
  /** In-flight set_secret punch-out the dock renders a form for (ephemeral). */
  pendingSecret: PendingSecret | null;
  /** In-flight connect_mcp punch-out the dock renders a connect form for
   *  (ephemeral). */
  pendingMcpConnect: PendingMcpConnect | null;
  /**
   * The dock's most recent chat session (persisted) plus the project/org it
   * belongs to. On reload the dock resumes it from the slug-routed ingress so
   * the conversation survives a refresh — the in-memory `agentChatStore`
   * doesn't. The context is stamped so resume only restores a session in the
   * project/org it started in: the builder threads `project_id` into its tools
   * and the session is org-scoped at the ingress, so a conversation doesn't
   * carry across a project/org switch.
   */
  lastSession: {
    id: string;
    projectId: number | null;
    orgId: string | null;
  } | null;

  toggleVisible: () => void;
  setVisible: (visible: boolean) => void;
  setFollowMode: (followMode: boolean) => void;
  setPage: (page: AgentBuilderPageContext) => void;
  /** Open the dock and prefill the composer with a prompt (not sent). */
  startAgentBuilder: (prompt: string, agentSlug?: string | null) => void;
  /** Mark a seed handled (no-op if a newer seed has since replaced it). */
  consumeSeed: (seq: number) => void;
  setPendingSecret: (pending: PendingSecret | null) => void;
  setPendingMcpConnect: (pending: PendingMcpConnect | null) => void;
  setLastSession: (
    session: {
      id: string;
      projectId: number | null;
      orgId: string | null;
    } | null,
  ) => void;
}

export const useAgentBuilderStore = create<AgentBuilderStore>()(
  persist(
    (set) => ({
      visible: false,
      followMode: true,
      page: { kind: "unknown" },
      seed: null,
      pendingSecret: null,
      pendingMcpConnect: null,
      lastSession: null,

      toggleVisible: () => set((s) => ({ visible: !s.visible })),
      setVisible: (visible) => set({ visible }),
      setFollowMode: (followMode) => set({ followMode }),
      setPage: (page) => set({ page }),
      startAgentBuilder: (prompt, agentSlug = null) =>
        set((s) => ({
          visible: true,
          seed: { seq: (s.seed?.seq ?? 0) + 1, prompt, agentSlug },
        })),
      consumeSeed: (seq) =>
        set((s) => (s.seed?.seq === seq ? { seed: null } : s)),
      setPendingSecret: (pendingSecret) => set({ pendingSecret }),
      setPendingMcpConnect: (pendingMcpConnect) => set({ pendingMcpConnect }),
      setLastSession: (lastSession) => set({ lastSession }),
    }),
    {
      name: "agent-builder-dock",
      storage: electronStorage,
      // Page + seed are ephemeral; persist the layout prefs + the last session
      // (with its project/org) so the dock can resume across a reload.
      partialize: (s) => ({
        visible: s.visible,
        followMode: s.followMode,
        lastSession: s.lastSession,
      }),
    },
  ),
);
