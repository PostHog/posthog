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
 * An action an MCP App card offers the user, as the card sends it to the host.
 *
 * A card is sandboxed HTML that any MCP server can supply, so it never hands the
 * host a URL. It sends the verb and the verb's own fields, and the host builds
 * the link with {@link buildActionUrl} using the scheme its own build registered.
 */
export interface McpAppComposeAction {
  kind: "compose";
  prompt: string;
  repo?: string;
}

export interface McpAppOpenSpaceAction {
  kind: "open_space";
  channel_id: string;
}

export interface McpAppOpenCanvasAction {
  kind: "open_canvas";
  channel_id: string;
  canvas_id: string;
}

export type McpAppAction =
  | McpAppComposeAction
  | McpAppOpenSpaceAction
  | McpAppOpenCanvasAction;

/** Percent-encode a required piece of a link, or null when it is missing or blank. */
function encodeRequired(value: string | undefined): string | null {
  return value && value.trim().length > 0 ? encodeURIComponent(value) : null;
}

/**
 * The link an action fires, or null when the action is missing a piece the link
 * needs. A partial link would land the user somewhere they didn't ask for, so
 * the caller drops the action instead.
 */
export function buildActionUrl(
  action: McpAppAction,
  scheme: string,
): string | null {
  switch (action.kind) {
    case "compose": {
      const prompt = encodeRequired(action.prompt);
      if (!prompt) {
        return null;
      }
      const repo = encodeRequired(action.repo);
      const query = repo ? `prompt=${prompt}&repo=${repo}` : `prompt=${prompt}`;
      return `${scheme}://new?${query}`;
    }
    case "open_space": {
      const channelId = encodeRequired(action.channel_id);
      return channelId ? `${scheme}://channel/${channelId}` : null;
    }
    case "open_canvas": {
      const channelId = encodeRequired(action.channel_id);
      const canvasId = encodeRequired(action.canvas_id);
      return channelId && canvasId
        ? `${scheme}://canvas/${channelId}/${canvasId}`
        : null;
    }
    default:
      return null;
  }
}
