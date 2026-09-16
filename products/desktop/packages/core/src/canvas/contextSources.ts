import type {
  McpRecommendedServer,
  McpServerInstallation,
} from "@posthog/api-client/types";
import {
  getInstallationStatus,
  type InstallationStatus,
} from "../mcp-servers/status";
import { isHttpUrl } from "./contextDocument";

/**
 * An external system a space can take context from. Each one is backed by an
 * MCP server in the catalog: agents in the space read what the person linked
 * through that server, so a link is only useful once the server is connected.
 */
export interface ContextSource {
  id: string;
  name: string;
  /** The catalog template's `icon_domain`; this is how a source finds its server. */
  iconDomain: string;
  /** What agents can do with a linked item once the server is connected. */
  purpose: string;
  placeholder: string;
  hosts: RegExp[];
  /** Turn a link or a short-hand into a target and what to call it, or null. */
  parse: (input: string) => ParsedSourceItem | null;
}

export interface ParsedSourceItem {
  target: string;
  title: string;
  /** "Slack channel", "Notion page": what one linked item is called. */
  label: string;
}

const HEX_ID = /-?[0-9a-f]{32}$/i;

function hostOf(input: string): string | null {
  if (!isHttpUrl(input)) return null;
  try {
    return new URL(input).host.toLowerCase();
  } catch {
    return null;
  }
}

function pathOf(input: string): string[] {
  try {
    return new URL(input).pathname.split("/").filter(Boolean);
  } catch {
    return [];
  }
}

function humanizeSlug(slug: string): string {
  return decodeURIComponent(slug).replace(HEX_ID, "").replace(/[-_]+/g, " ");
}

function lastSegmentTitle(input: string, fallback: string): string {
  const last = pathOf(input).pop();
  const title = last ? humanizeSlug(last).trim() : "";
  return title || fallback;
}

// A channel short-hand becomes Slack's own redirect URL, which opens in the
// app and which agents resolve by name through the Slack server.
const SLACK_CHANNEL_RE = /^#([a-z0-9][a-z0-9._-]*)$/i;
const SLACK_ARCHIVE_RE = /^\/archives\/([A-Z0-9]+)(?:\/(p\d+))?/;

const slack: ContextSource = {
  id: "slack",
  name: "Slack",
  iconDomain: "slack.com",
  purpose: "Agents read the channels and threads you link.",
  placeholder: "#channel, or a link to a channel or thread",
  hosts: [/(^|\.)slack\.com$/],
  parse: (input) => {
    const shorthand = SLACK_CHANNEL_RE.exec(input);
    if (shorthand) {
      return {
        target: `https://slack.com/app_redirect?channel=${encodeURIComponent(shorthand[1])}`,
        title: `#${shorthand[1]}`,
        label: "Slack channel",
      };
    }
    if (!matchesHost(slack, input)) return null;
    const url = new URL(input);
    const redirected = url.searchParams.get("channel");
    if (url.pathname === "/app_redirect" && redirected) {
      return {
        target: input,
        title: `#${redirected}`,
        label: "Slack channel",
      };
    }
    const archive = SLACK_ARCHIVE_RE.exec(url.pathname);
    if (archive?.[2]) {
      return { target: input, title: "Slack thread", label: "Slack thread" };
    }
    if (archive) {
      return {
        target: input,
        title: `Channel ${archive[1]}`,
        label: "Slack channel",
      };
    }
    return { target: input, title: "Slack link", label: "Slack link" };
  },
};

const notion: ContextSource = {
  id: "notion",
  name: "Notion",
  iconDomain: "notion.com",
  purpose: "Agents read the pages and databases you link.",
  placeholder: "Link to a Notion page or database",
  hosts: [/(^|\.)notion\.(so|com|site)$/],
  parse: (input) =>
    matchesHost(notion, input)
      ? {
          target: input,
          title: lastSegmentTitle(input, "Notion page"),
          label: "Notion page",
        }
      : null,
};

const linear: ContextSource = {
  id: "linear",
  name: "Linear",
  iconDomain: "linear.app",
  purpose: "Agents read the issues and projects you link.",
  placeholder: "Link to a Linear issue or project",
  hosts: [/(^|\.)linear\.app$/],
  parse: (input) => {
    if (!matchesHost(linear, input)) return null;
    const [, kind, id] = pathOf(input);
    if (kind === "issue" && id) {
      return { target: input, title: id.toUpperCase(), label: "Linear issue" };
    }
    if (kind === "project" && id) {
      return {
        target: input,
        title: humanizeSlug(id).trim() || "Linear project",
        label: "Linear project",
      };
    }
    return { target: input, title: "Linear link", label: "Linear link" };
  },
};

const atlassian: ContextSource = {
  id: "atlassian",
  name: "Atlassian",
  iconDomain: "atlassian.com",
  purpose: "Agents read the Jira issues and Confluence pages you link.",
  placeholder: "Link to a Jira issue or a Confluence page",
  hosts: [/(^|\.)atlassian\.(net|com)$/],
  parse: (input) => {
    if (!matchesHost(atlassian, input)) return null;
    const path = pathOf(input);
    if (path[0] === "browse" && path[1]) {
      return { target: input, title: path[1], label: "Jira issue" };
    }
    if (path[0] === "wiki") {
      return {
        target: input,
        title: lastSegmentTitle(input, "Confluence page"),
        label: "Confluence page",
      };
    }
    return { target: input, title: "Atlassian link", label: "Atlassian link" };
  },
};

const figma: ContextSource = {
  id: "figma",
  name: "Figma",
  iconDomain: "figma.com",
  purpose: "Agents read the files and prototypes you link.",
  placeholder: "Link to a Figma file",
  hosts: [/(^|\.)figma\.com$/],
  parse: (input) =>
    matchesHost(figma, input)
      ? {
          target: input,
          title: lastSegmentTitle(input, "Figma file"),
          label: "Figma file",
        }
      : null,
};

const gitlab: ContextSource = {
  id: "gitlab",
  name: "GitLab",
  iconDomain: "gitlab.com",
  purpose: "Agents read the repositories, issues, and merge requests you link.",
  placeholder: "Link to a GitLab repository, issue, or merge request",
  hosts: [/(^|\.)gitlab\.com$/],
  parse: (input) => {
    if (!matchesHost(gitlab, input)) return null;
    const path = pathOf(input);
    const marker = path.indexOf("-");
    const kind = marker >= 0 ? path[marker + 1] : null;
    if (kind === "issues") {
      return {
        target: input,
        title: `#${path[marker + 2] ?? ""}`.trim(),
        label: "GitLab issue",
      };
    }
    if (kind === "merge_requests") {
      return {
        target: input,
        title: `!${path[marker + 2] ?? ""}`.trim(),
        label: "GitLab merge request",
      };
    }
    return {
      target: input,
      title: path.slice(0, 2).join("/") || "GitLab repository",
      label: "GitLab repository",
    };
  },
};

const sentry: ContextSource = {
  id: "sentry",
  name: "Sentry",
  iconDomain: "sentry.io",
  purpose: "Agents read the issues you link.",
  placeholder: "Link to a Sentry issue",
  hosts: [/(^|\.)sentry\.io$/],
  parse: (input) => {
    if (!matchesHost(sentry, input)) return null;
    const path = pathOf(input);
    const at = path.indexOf("issues");
    return at >= 0 && path[at + 1]
      ? { target: input, title: `Issue ${path[at + 1]}`, label: "Sentry issue" }
      : { target: input, title: "Sentry link", label: "Sentry link" };
  },
};

const granola: ContextSource = {
  id: "granola",
  name: "Granola",
  iconDomain: "granola.ai",
  purpose: "Agents read the meeting notes you link.",
  placeholder: "Link to a Granola note",
  hosts: [/(^|\.)granola\.ai$/],
  parse: (input) =>
    matchesHost(granola, input)
      ? {
          target: input,
          title: lastSegmentTitle(input, "Granola note"),
          label: "Granola note",
        }
      : null,
};

const hubspot: ContextSource = {
  id: "hubspot",
  name: "HubSpot",
  iconDomain: "hubspot.com",
  purpose: "Agents read the companies, contacts, and deals you link.",
  placeholder: "Link to a HubSpot record",
  hosts: [/(^|\.)hubspot\.com$/],
  parse: (input) =>
    matchesHost(hubspot, input)
      ? { target: input, title: "HubSpot record", label: "HubSpot record" }
      : null,
};

const box: ContextSource = {
  id: "box",
  name: "Box",
  iconDomain: "box.com",
  purpose: "Agents read the files and folders you link.",
  placeholder: "Link to a Box file or folder",
  hosts: [/(^|\.)box\.com$/],
  parse: (input) =>
    matchesHost(box, input)
      ? {
          target: input,
          title: lastSegmentTitle(input, "Box file"),
          label: "Box file",
        }
      : null,
};

/** Order is the order the picker shows them in. */
export const CONTEXT_SOURCES: readonly ContextSource[] = [
  slack,
  notion,
  linear,
  atlassian,
  figma,
  gitlab,
  sentry,
  granola,
  hubspot,
  box,
];

function matchesHost(source: ContextSource, input: string): boolean {
  const host = hostOf(input);
  return host !== null && source.hosts.some((pattern) => pattern.test(host));
}

/** The source a link belongs to, from its host alone. */
export function detectContextSource(target: string): ContextSource | null {
  return CONTEXT_SOURCES.find((source) => matchesHost(source, target)) ?? null;
}

/**
 * What the person typed, read as an item of one source. A URL names its source
 * by host; a short-hand like `#growth` only parses when that source is chosen.
 */
export function parseContextSourceInput(
  input: string,
  chosen: ContextSource | null,
): { source: ContextSource; item: ParsedSourceItem } | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  if (chosen) {
    const item = chosen.parse(trimmed);
    if (item) return { source: chosen, item };
  }
  const source = detectContextSource(trimmed);
  if (!source) return null;
  const item = source.parse(trimmed);
  return item ? { source, item } : null;
}

/** The source a catalog template stands for, matched on its brand domain. */
export function contextSourceForTemplate(template: {
  icon_domain?: string | null;
  name?: string | null;
}): ContextSource | null {
  const domain = template.icon_domain?.toLowerCase() ?? "";
  return (
    CONTEXT_SOURCES.find((source) => source.iconDomain === domain) ??
    CONTEXT_SOURCES.find(
      (source) => source.name.toLowerCase() === template.name?.toLowerCase(),
    ) ??
    null
  );
}

export type ContextSourceStatus = InstallationStatus | "not_connected";

export interface ResolvedContextSource {
  source: ContextSource;
  template: McpRecommendedServer;
  installation: McpServerInstallation | null;
  status: ContextSourceStatus;
  /** A key or token cannot be entered here, so this source connects from the MCP servers page. */
  needsCredentials: boolean;
}

/**
 * Join the sources with the MCP catalog and the team's installations. A source
 * only appears when the catalog has a server for it, and reads as connected
 * only when that server is installed and authorized, because that is what lets
 * agents open the links.
 */
export function resolveContextSources(
  servers: readonly McpRecommendedServer[],
  installations: readonly McpServerInstallation[],
): ResolvedContextSource[] {
  const byTemplate = new Map<string, McpServerInstallation>();
  for (const installation of installations) {
    if (installation.template_id) {
      byTemplate.set(installation.template_id, installation);
    }
  }
  const resolved: ResolvedContextSource[] = [];
  for (const source of CONTEXT_SOURCES) {
    const template = servers.find(
      (candidate) => contextSourceForTemplate(candidate)?.id === source.id,
    );
    if (!template) continue;
    const installation = byTemplate.get(template.id) ?? null;
    resolved.push({
      source,
      template,
      installation,
      status: installation
        ? getInstallationStatus(installation)
        : "not_connected",
      needsCredentials: (template.auth_type ?? "oauth") !== "oauth",
    });
  }
  return resolved;
}
