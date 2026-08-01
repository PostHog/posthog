import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useRef } from "react";
import type { ClientToolHandler } from "../hooks/useAgentChat";
import { useAgentBuilderStore } from "./agentBuilderStore";

/**
 * The `kind:'client'` tool ids the agent-builder dock can fulfil — sent to the
 * runner as `supported_client_tools` at /run so it exposes only these to the
 * model. Keep in sync with the handlers below (plus the built-in
 * toast/get_context). `set_secret`/`connect_mcp` are interactive punch-outs.
 */
export const AGENT_BUILDER_CLIENT_TOOLS = [
  "set_secret",
  "connect_mcp",
  "focus_tab",
  "focus_file",
  "focus_spec_section",
  "focus_revision",
  "focus_session",
  "toast",
  "get_context",
] as const;

/**
 * The agent builder's UI-driving client tools. The agent calls these to steer the
 * user's screen (`focus_*`, which navigate code's agent routes and report back
 * `{ focused }`) and to set secrets (`set_secret`, an interactive punch-out:
 * park the call and render a form — see the dock). Returning `null` defers to
 * the built-in toast/get_context handlers.
 *
 * `focus_*` navigations are gated by follow-mode: when off, they report
 * `{ focused: false, reason: "user_paused_follow" }` instead of moving the UI.
 */
export function useAgentBuilderClientTools(): ClientToolHandler {
  const navigate = useNavigate();
  const client = useAuthenticatedClient();
  const followMode = useAgentBuilderStore((s) => s.followMode);
  const setPendingSecret = useAgentBuilderStore((s) => s.setPendingSecret);
  const setPendingMcpConnect = useAgentBuilderStore(
    (s) => s.setPendingMcpConnect,
  );
  const page = useAgentBuilderStore((s) => s.page);
  const followRef = useRef(followMode);
  followRef.current = followMode;
  // Latest page context without re-creating the handler each render — resolves
  // the revision a `set_secret` punch-out targets when the agent omits one.
  const pageRef = useRef(page);
  pageRef.current = page;

  return useCallback(
    async (data) => {
      const args = (data.args ?? {}) as Record<string, unknown>;
      const str = (v: unknown) => (typeof v === "string" ? v : undefined);

      // Env keys and spec edits are revision-scoped, but the punch-out tool
      // schemas don't define `revision_id`, so the agent usually omits it.
      // Resolve the target: explicit arg → the revision the user is viewing on
      // this agent's config page → API fallback. Preference matters because
      // secrets only copy forward at draft creation and spec PATCHes only land
      // on drafts: a *new* secret or MCP connection targets the draft being
      // authored, while a rotation targets what's running (live).
      const resolveRevision = async (
        agentSlug: string,
        prefer: "live" | "draft",
      ): Promise<string | undefined> => {
        const p = pageRef.current;
        // The viewed revision only stands in for authoring flows: a rotation
        // must reach what's running even while the user is viewing a draft.
        if (
          prefer === "draft" &&
          p.kind === "agent-config" &&
          p.slug === agentSlug &&
          p.revision
        ) {
          return p.revision;
        }
        try {
          // A revision's `state` stays "ready" when promoted — live is the
          // application's `live_revision` pointer, not a revision state.
          const [app, revisions] = await Promise.all([
            client.getAgentApplication(agentSlug),
            client.listAgentRevisions(agentSlug),
          ]);
          const live = app?.live_revision ?? undefined;
          const draft = revisions.find((r) => r.state === "draft")?.id;
          const newest = revisions[0]?.id;
          return prefer === "draft"
            ? (draft ?? live ?? newest)
            : (live ?? draft ?? newest);
        } catch {
          return undefined;
        }
      };

      // An explicit `revision_id` must belong to `agent_slug` before we park
      // the punch-out. The nested env/spec routes reject mismatches
      // server-side anyway, but that failure would only surface at submit —
      // after the user has already typed a secret into a doomed form.
      const verifyExplicitRevision = async (
        agentSlug: string,
        revisionId: string,
      ): Promise<boolean> => {
        const revision = await client
          .getAgentRevision(agentSlug, revisionId)
          .catch(() => null);
        return revision != null;
      };

      // set_secret — interactive punch-out. Park the call (defer) and render a
      // form; the dock PUTs the key and wakes the session on submit.
      if (data.tool_id === "set_secret") {
        const agentSlug = str(args.agent_slug);
        const secret = str(args.secret);
        if (!agentSlug) return { error: "missing_arg: agent_slug" };
        if (!secret) return { error: "missing_arg: secret" };
        const mode = args.mode === "rotate" ? "rotate" : "set";
        const explicit = str(args.revision_id);
        if (explicit && !(await verifyExplicitRevision(agentSlug, explicit))) {
          return { error: `revision_not_found: ${explicit} on ${agentSlug}` };
        }
        const revisionId =
          explicit ??
          (await resolveRevision(
            agentSlug,
            mode === "rotate" ? "live" : "draft",
          ));
        if (!revisionId) return { error: `no_target_revision: ${agentSlug}` };
        setPendingSecret({
          callId: data.call_id,
          agentSlug,
          revisionId,
          secret,
          mode,
          purpose: str(args.purpose),
        });
        return { defer: true };
      }

      // connect_mcp — interactive punch-out. Park the call and render a prefilled
      // connect form; the dock runs the native OAuth/api-key connect (auth never
      // touches the agent), writes the resulting mcps[].connection onto the
      // target agent's spec, and wakes the session. Same revision resolution as
      // set_secret.
      if (data.tool_id === "connect_mcp") {
        const agentSlug = str(args.agent_slug);
        if (!agentSlug) return { error: "missing_arg: agent_slug" };
        const explicit = str(args.revision_id);
        if (explicit && !(await verifyExplicitRevision(agentSlug, explicit))) {
          return { error: `revision_not_found: ${explicit} on ${agentSlug}` };
        }
        const revisionId =
          explicit ?? (await resolveRevision(agentSlug, "draft"));
        if (!revisionId) return { error: `no_target_revision: ${agentSlug}` };
        setPendingMcpConnect({
          callId: data.call_id,
          agentSlug,
          revisionId,
          name: str(args.name),
          url: str(args.url),
          purpose: str(args.purpose),
        });
        return { defer: true };
      }

      if (!data.tool_id.startsWith("focus_")) return null;
      const slug = str(args.slug);
      if (!followRef.current) {
        return { result: { focused: false, reason: "user_paused_follow" } };
      }
      if (!slug) {
        return { result: { focused: false, reason: "missing_slug" } };
      }
      const params = { idOrSlug: slug };

      switch (data.tool_id) {
        case "focus_tab": {
          const tab = str(args.tab) ?? "overview";
          switch (tab) {
            case "configuration":
              navigate({
                to: "/code/agents/applications/$idOrSlug/configuration",
                params,
              });
              break;
            case "sessions":
              navigate({
                to: "/code/agents/applications/$idOrSlug/sessions",
                params,
              });
              break;
            case "memory":
              navigate({
                to: "/code/agents/applications/$idOrSlug/memory",
                params,
              });
              break;
            case "approvals":
              navigate({
                to: "/code/agents/applications/$idOrSlug/approvals",
                params,
              });
              break;
            case "observability":
              navigate({
                to: "/code/agents/applications/$idOrSlug/observability",
                params,
              });
              break;
            case "chat":
              navigate({
                to: "/code/agents/applications/$idOrSlug/chat",
                params,
              });
              break;
            default:
              navigate({
                to: "/code/agents/applications/$idOrSlug",
                params,
              });
          }
          return { result: { focused: true } };
        }
        case "focus_file":
          navigate({
            to: "/code/agents/applications/$idOrSlug/configuration",
            params,
            search: { node: str(args.path) },
          });
          return { result: { focused: true } };
        case "focus_spec_section":
          navigate({
            to: "/code/agents/applications/$idOrSlug/configuration",
            params,
            search: { node: str(args.section) },
          });
          return { result: { focused: true } };
        case "focus_revision":
          navigate({
            to: "/code/agents/applications/$idOrSlug/configuration",
            params,
            search: { revision: str(args.revisionId) },
          });
          return { result: { focused: true } };
        case "focus_session": {
          const sessionId = str(args.sessionId);
          if (!sessionId) {
            return { result: { focused: false, reason: "missing_session_id" } };
          }
          navigate({
            to: "/code/agents/applications/$idOrSlug/sessions/$sessionId",
            params: { idOrSlug: slug, sessionId },
          });
          return { result: { focused: true } };
        }
        default:
          return { result: { focused: false, reason: "unknown_focus_target" } };
      }
    },
    [navigate, client, setPendingSecret, setPendingMcpConnect],
  );
}
