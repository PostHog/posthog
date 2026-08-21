import { scoutSkillSlug } from "./scout-naming";

export const DEEPLINK_PROTOCOL_PRODUCTION = "posthog-code";
export const DEEPLINK_PROTOCOL_DEVELOPMENT = "posthog-code-dev";

export function getDeeplinkProtocol(isDevBuild: boolean): string {
  return isDevBuild
    ? DEEPLINK_PROTOCOL_DEVELOPMENT
    : DEEPLINK_PROTOCOL_PRODUCTION;
}

export function isPostHogCodeDeeplink(
  href: string | undefined,
): href is string {
  if (!href) return false;
  try {
    const protocol = new URL(href).protocol;
    return (
      protocol === `${DEEPLINK_PROTOCOL_PRODUCTION}:` ||
      protocol === `${DEEPLINK_PROTOCOL_DEVELOPMENT}:`
    );
  } catch {
    return false;
  }
}

export function buildInboxDeeplink(
  reportId: string,
  title: string | null | undefined,
  { isDevBuild }: { isDevBuild: boolean },
): string {
  const base = `${getDeeplinkProtocol(isDevBuild)}://inbox/${reportId}`;
  const slug = title
    ? title
        .normalize("NFD")
        .replace(/\p{M}/gu, "")
        .replace(/[^a-zA-Z0-9_.~]+/g, (run) =>
          run.includes(":") && /[^:]/.test(run) ? "--" : "-",
        )
        .replace(/^-+|-+$/g, "")
    : "";
  return slug ? `${base}/${slug}` : base;
}

/**
 * Build a canonical deep link to a loop's detail page
 * (`<scheme>://loop/<loopId>`). The inbound side lives in the `loop` handler
 * (`LoopLinkService`), which routes to `/code/loops/<loopId>`.
 */
export function buildLoopDeeplink(
  loopId: string,
  { isDevBuild }: { isDevBuild: boolean },
): string {
  return `${getDeeplinkProtocol(isDevBuild)}://loop/${encodeURIComponent(loopId)}`;
}

/**
 * Build a canonical deep link to a scout's detail page, optionally focused on a
 * specific finding (`<scheme>://scout/<skillSlug>?finding=<id>`).
 *
 * `skillName` may be the full scout skill name (`signals-scout-error-tracking`)
 * or an already-stripped route slug (`error-tracking`); the `signals-scout-`
 * prefix is removed so the path always matches the renderer route param.
 */
export function buildScoutDeeplink(
  skillName: string,
  findingId: string | null | undefined,
  { isDevBuild }: { isDevBuild: boolean },
): string {
  const slug = scoutSkillSlug(skillName);
  const base = `${getDeeplinkProtocol(isDevBuild)}://scout/${encodeURIComponent(slug)}`;
  return findingId ? `${base}?finding=${encodeURIComponent(findingId)}` : base;
}

export interface GitHubIssueRef {
  owner: string;
  repo: string;
  number: number;
}

export function decodePlanBase64(encoded: string): string | null {
  try {
    const normalized = encoded
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .replace(/ /g, "+");
    const padding = (4 - (normalized.length % 4)) % 4;
    const padded = normalized + "=".repeat(padding);
    if (!/^[A-Za-z0-9+/]*=*$/.test(padded)) return null;
    return Buffer.from(padded, "base64").toString("utf-8");
  } catch {
    return null;
  }
}

export function parseGitHubIssueUrl(url: string): GitHubIssueRef | null {
  try {
    const parsed = new URL(url);
    if (parsed.hostname !== "github.com") return null;

    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parts.length !== 4 || parts[2] !== "issues") return null;

    const issueNumber = Number.parseInt(parts[3], 10);
    if (Number.isNaN(issueNumber) || issueNumber <= 0) return null;

    return { owner: parts[0], repo: parts[1], number: issueNumber };
  } catch {
    return null;
  }
}

export interface NewTaskSharedParams {
  repo?: string;
  mode?: string;
  model?: string;
}

export type NewTaskLinkPayload =
  | ({ action: "new"; prompt?: string } & NewTaskSharedParams)
  | ({ action: "plan"; plan: string } & NewTaskSharedParams)
  | ({
      action: "issue";
      url: string;
      owner: string;
      issueRepo: string;
      issueNumber: number;
    } & NewTaskSharedParams);

/**
 * An action an agent offers the user as a button. It names a verb and the verb's
 * own fields rather than a URL, and the host builds the link itself with
 * {@link buildActionUrl}. Agent output can carry text from anywhere, so a URL it
 * picked and the user was invited to click would be a phishing primitive.
 */
export interface AgentComposeAction {
  kind: "compose";
  prompt: string;
  repo?: string;
}

export interface AgentOpenSpaceAction {
  kind: "open_space";
  channel_id: string;
}

export interface AgentOpenCanvasAction {
  kind: "open_canvas";
  channel_id: string;
  canvas_id: string;
}

export type AgentAction =
  | AgentComposeAction
  | AgentOpenSpaceAction
  | AgentOpenCanvasAction;

/**
 * The action is already validated by `agentActionSchema`, which rejects a blank required field,
 * so every branch can build a whole link. Keep that guarantee at the schema rather than returning
 * a partial link from here.
 */
export function buildActionUrl(action: AgentAction, scheme: string): string {
  switch (action.kind) {
    case "compose": {
      const prompt = `prompt=${encodeURIComponent(action.prompt)}`;
      const query = action.repo
        ? `${prompt}&repo=${encodeURIComponent(action.repo)}`
        : prompt;
      return `${scheme}://new?${query}`;
    }
    case "open_space":
      return `${scheme}://channel/${encodeURIComponent(action.channel_id)}`;
    case "open_canvas":
      return `${scheme}://canvas/${encodeURIComponent(action.channel_id)}/${encodeURIComponent(action.canvas_id)}`;
  }
}
