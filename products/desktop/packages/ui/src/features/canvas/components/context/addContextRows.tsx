import { FileTextIcon, LinkIcon } from "@phosphor-icons/react";
import {
  CONTEXT_OBJECT_KIND_LABELS,
  type ContextLink,
  type ContextObject,
  isHttpUrl,
  parsePostHogObjectUrl,
} from "@posthog/core/canvas/contextDocument";
import { parseContextSourceInput } from "@posthog/core/canvas/contextSources";
import type {
  ContextSourceState,
  ContextSources,
} from "@posthog/ui/features/canvas/hooks/useContextSources";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import type { ReactNode } from "react";
import { KIND_ICONS } from "./kindIcons";

/** What the input is read as. A source scope also makes short-hands like `#growth` parse. */
export type AddContextScope =
  | { kind: "posthog" }
  | { kind: "file" }
  | { kind: "link" }
  | { kind: "source"; state: ContextSourceState };

export interface AddContextRow {
  id: string;
  icon: ReactNode;
  label: string;
  /** Trailing text at the right edge of the row: what selecting the row does. */
  detail?: string;
  subtitle?: string;
  tone?: "default" | "warning";
  busy?: boolean;
  run: () => void;
}

export interface AddContextSection {
  label: string;
  items: AddContextRow[];
}

/** The one thing the current input adds, once it parses. */
export type Addition =
  | { kind: "object"; object: ContextObject }
  | {
      kind: "link";
      link: ContextLink;
      label: string;
      /** The source the link belongs to, when the catalog has a server for it. */
      state: ContextSourceState | null;
    }
  | { kind: "file"; link: ContextLink };

export interface AddContextActions {
  setScope: (scope: AddContextScope) => void;
  connect: (state: ContextSourceState) => void;
  openServers: () => void;
  add: () => void;
}

export interface AddContextView {
  sections: AddContextSection[];
  addition: Addition | null;
  /** Set when the addition's source is not connected, so adding waits on it. */
  blockedBy: ContextSourceState | null;
  emptyMessage: string | null;
}

const PATH_RE = /^(?!#)[^\s]+(\/[^\s]+|\.[a-z0-9]{1,8})$/i;

export function titleFromTarget(target: string): string {
  if (!isHttpUrl(target)) return target;
  try {
    const url = new URL(target);
    const last = url.pathname.split("/").filter(Boolean).pop();
    return last ? decodeURIComponent(last).replace(/[-_]+/g, " ") : url.host;
  } catch {
    return target;
  }
}

function hostOf(target: string): string {
  try {
    return new URL(target).host;
  } catch {
    return target;
  }
}

export function parseAddition(
  query: string,
  scope: AddContextScope | null,
  sources: ContextSources,
): Addition | null {
  const input = query.trim();
  if (!input) return null;
  if (scope?.kind !== "file") {
    if (scope?.kind !== "source") {
      const object = parsePostHogObjectUrl(input);
      if (object) {
        return {
          kind: "object",
          object: {
            kind: object.kind,
            url: input,
            title: `${CONTEXT_OBJECT_KIND_LABELS[object.kind]} ${object.id}`,
          },
        };
      }
    }
    const external = parseContextSourceInput(
      input,
      scope?.kind === "source" ? scope.state.source : null,
    );
    if (external) {
      return {
        kind: "link",
        link: {
          target: external.item.target,
          title: external.item.title,
          note: "",
        },
        label: external.item.label,
        state: sources.byId(external.source.id) ?? null,
      };
    }
    if (isHttpUrl(input)) {
      return {
        kind: "link",
        link: { target: input, title: titleFromTarget(input), note: "" },
        label: "Link",
        state: null,
      };
    }
  }
  if (scope?.kind === "file" || (scope === null && PATH_RE.test(input))) {
    return { kind: "file", link: { target: input, title: input, note: "" } };
  }
  return null;
}

/** What the input expects once a scope is chosen; doubles as the input's placeholder. */
export function scopeHint(scope: AddContextScope): string {
  switch (scope.kind) {
    case "source":
      return scope.state.source.placeholder;
    case "posthog":
      return "Paste the URL of an insight, dashboard, flag, experiment, or any PostHog object";
    case "file":
      return "Type a path in this repository, like docs/checkout.md";
    case "link":
      return "Paste a URL";
  }
}

export function scopeLabel(scope: AddContextScope): string {
  switch (scope.kind) {
    case "source":
      return scope.state.source.name;
    case "posthog":
      return "PostHog";
    case "file":
      return "Repository file";
    case "link":
      return "Link";
  }
}

export function connectLabel(state: ContextSourceState): string {
  if (state.needsCredentials) return "Open MCP servers";
  if (state.status === "needs_reauth") return "Reconnect";
  if (state.status === "pending_oauth") return "Finish authorizing";
  return "Connect";
}

/** Why a link from this source is not readable yet, in the status's own words. */
export function unconnectedWarning(state: ContextSourceState): string {
  const name = state.source.name;
  if (state.needsCredentials) {
    return `${name} is not connected. It needs an API key, so it connects from the MCP servers page.`;
  }
  if (state.status === "needs_reauth") {
    return `${name} needs to be authorized again before agents can read this.`;
  }
  if (state.status === "pending_oauth") {
    return `Authorization for ${name} was not finished, so agents cannot read this yet.`;
  }
  return `${name} is not connected, so agents cannot read this yet.`;
}

function connectSubtitle(state: ContextSourceState): string {
  const name = state.source.name;
  if (state.needsCredentials) {
    return `Needs an API key, so it connects from the MCP servers page.`;
  }
  if (state.status === "needs_reauth") {
    return `${name} needs to be authorized again before agents can read what you link.`;
  }
  if (state.status === "pending_oauth") {
    return `Authorization was started but not finished. Finishing it opens ${name} in your browser.`;
  }
  return state.source.purpose;
}

function connectRow(
  state: ContextSourceState,
  actions: AddContextActions,
): AddContextRow {
  const name = state.source.name;
  return {
    id: `connect:${state.source.id}`,
    icon: <ServerIcon iconDomain={state.source.iconDomain} size={16} />,
    label: name,
    subtitle: connectSubtitle(state),
    detail: state.connecting ? `Waiting for ${name}` : connectLabel(state),
    busy: state.connecting,
    run: () =>
      state.needsCredentials ? actions.openServers() : actions.connect(state),
  };
}

function additionRow(
  addition: Addition,
  blockedBy: ContextSourceState | null,
  actions: AddContextActions,
): AddContextRow {
  if (addition.kind === "object") {
    const kindLabel = CONTEXT_OBJECT_KIND_LABELS[addition.object.kind];
    return {
      id: "add",
      icon: KIND_ICONS[addition.object.kind],
      label: kindLabel,
      subtitle: hostOf(addition.object.url),
      run: actions.add,
    };
  }
  if (addition.kind === "file") {
    return {
      id: "add",
      icon: <FileTextIcon size={14} />,
      label: addition.link.target,
      subtitle: "Repository file",
      run: actions.add,
    };
  }
  const { link, label, state } = addition;
  const icon = state ? (
    <ServerIcon iconDomain={state.source.iconDomain} size={16} />
  ) : (
    <LinkIcon size={14} />
  );
  if (blockedBy) {
    const name = blockedBy.source.name;
    return {
      id: "add",
      icon,
      label: link.title,
      subtitle: blockedBy.connecting
        ? `Finish authorizing ${name} in your browser, then add the link.`
        : unconnectedWarning(blockedBy),
      tone: "warning",
      detail: blockedBy.connecting
        ? `Waiting for ${name}`
        : `${connectLabel(blockedBy)} ${blockedBy.needsCredentials ? "" : name}`.trim(),
      busy: blockedBy.connecting,
      run: () =>
        blockedBy.needsCredentials
          ? actions.openServers()
          : actions.connect(blockedBy),
    };
  }
  return {
    id: "add",
    icon,
    label: link.title,
    subtitle:
      link.title === label
        ? hostOf(link.target)
        : `${label} · ${hostOf(link.target)}`,
    run: actions.add,
  };
}

function scopeRows(actions: AddContextActions): AddContextRow[] {
  return [
    {
      id: "scope:posthog",
      icon: <ServerIcon iconDomain="posthog.com" size={16} />,
      label: "PostHog object",
      subtitle: "An insight, dashboard, flag, experiment, or any object URL",
      run: () => actions.setScope({ kind: "posthog" }),
    },
    {
      id: "scope:file",
      icon: <FileTextIcon size={14} />,
      label: "Repository file",
      subtitle: "A path in this repository, like docs/checkout.md",
      run: () => actions.setScope({ kind: "file" }),
    },
    {
      id: "scope:link",
      icon: <LinkIcon size={14} />,
      label: "Link",
      subtitle: "Any web page",
      run: () => actions.setScope({ kind: "link" }),
    },
  ];
}

function matches(row: AddContextRow, needle: string): boolean {
  const haystack = `${row.label} ${row.subtitle ?? ""}`.toLowerCase();
  return haystack.includes(needle);
}

/**
 * Everything the palette shows for the current input. A parsed link or object
 * becomes the one "Add" row; anything else is read as a search over the
 * sources, so a person can find and connect a source from the same box they
 * paste into.
 */
export function buildAddContextView(
  query: string,
  scope: AddContextScope | null,
  sources: ContextSources,
  actions: AddContextActions,
): AddContextView {
  const addition = parseAddition(query, scope, sources);
  const blockedBy =
    addition?.kind === "link" &&
    addition.state &&
    addition.state.status !== "connected"
      ? addition.state
      : null;

  if (addition) {
    return {
      sections: [
        {
          label: "Add to this space",
          items: [additionRow(addition, blockedBy, actions)],
        },
      ],
      addition,
      blockedBy,
      emptyMessage: null,
    };
  }

  const input = query.trim();
  if (scope) {
    const hint = scopeHint(scope);
    return {
      sections: [],
      addition: null,
      blockedBy: null,
      emptyMessage: input ? `${hint}. This does not look like one yet.` : hint,
    };
  }

  const connected = sources.sources.filter(
    (state) => state.status === "connected",
  );
  const unconnected = sources.sources.filter(
    (state) => state.status !== "connected",
  );
  const all: AddContextSection[] = [
    { label: "Add", items: scopeRows(actions) },
    {
      label: "Connected sources",
      items: connected.map((state) => ({
        id: `source:${state.source.id}`,
        icon: <ServerIcon iconDomain={state.source.iconDomain} size={16} />,
        label: state.source.name,
        subtitle: state.source.placeholder,
        run: () => actions.setScope({ kind: "source", state }),
      })),
    },
    {
      label: "Connect a source",
      items: unconnected.map((state) => connectRow(state, actions)),
    },
  ];
  const needle = input.toLowerCase();
  const sections = all
    .map((section) => ({
      ...section,
      items: needle
        ? section.items.filter((row) => matches(row, needle))
        : section.items,
    }))
    .filter((section) => section.items.length > 0);
  return {
    sections,
    addition: null,
    blockedBy: null,
    emptyMessage:
      sections.length === 0
        ? `No source called "${input}". Paste a link or a repository path to add it.`
        : null,
  };
}
