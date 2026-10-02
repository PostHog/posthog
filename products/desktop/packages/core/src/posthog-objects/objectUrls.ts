import {
  APP_HOST_ALIASES,
  OBJECT_KIND_DATA,
  type ObjectKindData,
  RESERVED_URL_IDS,
} from "../inbox/objectKinds.generated";

export interface PostHogLinkContext {
  appUrl: string;
  projectId: number | string;
}

export interface PostHogObjectUrlRef {
  kind: string;
  id: string;
  href: string;
}

interface UrlTemplate {
  kind: string;
  segments: string[];
  idIndex: number;
  paramSource: "query" | "fragment" | null;
  paramKey: string;
  queryNode: boolean;
  guard: RegExp | null;
  idIsBody: boolean;
}

function pathSegments(path: string): string[] {
  return path.split("/").filter(Boolean);
}

function compileTemplate(
  kind: string,
  data: ObjectKindData,
  template: string,
): UrlTemplate {
  const hashIndex = template.indexOf("#");
  const beforeHash = hashIndex === -1 ? template : template.slice(0, hashIndex);
  const fragment = hashIndex === -1 ? "" : template.slice(hashIndex + 1);
  const queryIndex = beforeHash.indexOf("?");
  const path = queryIndex === -1 ? beforeHash : beforeHash.slice(0, queryIndex);
  const query = queryIndex === -1 ? "" : beforeHash.slice(queryIndex + 1);
  const segments = pathSegments(path);
  const [paramKey = "", placeholder = ""] = (query || fragment).split("=");
  return {
    kind,
    segments,
    idIndex: segments.indexOf("{id}"),
    paramSource: query ? "query" : fragment ? "fragment" : null,
    paramKey,
    queryNode: placeholder === "{query}",
    guard: data.idPattern ? new RegExp(data.idPattern) : null,
    idIsBody: data.idIsBody,
  };
}

const URL_TEMPLATES: UrlTemplate[] = (
  Object.entries(OBJECT_KIND_DATA) as [string, ObjectKindData][]
).flatMap(([kind, data]) =>
  [data.pathTemplate, ...data.urlAliases]
    .filter((template): template is string => template !== null)
    .map((template) => compileTemplate(kind, data, template)),
);

function appHost(host: string): string {
  const lower = host.toLowerCase();
  return APP_HOST_ALIASES[lower] ?? lower;
}

function decodePart(part: string): string {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}

function hogqlFromQueryNode(raw: string): string | null {
  let node: unknown;
  try {
    node = JSON.parse(raw);
  } catch {
    return null;
  }
  for (let depth = 0; depth < 3; depth++) {
    if (typeof node !== "object" || node === null) return null;
    const record = node as Record<string, unknown>;
    if (record.kind === "HogQLQuery" && typeof record.query === "string") {
      return record.query;
    }
    node = record.source;
  }
  return null;
}

function matchTemplate(
  template: UrlTemplate,
  segments: string[],
  url: URL,
): string | null {
  if (template.idIndex !== -1) {
    if (segments.length <= template.idIndex) return null;
    for (let i = 0; i < template.idIndex; i++) {
      if (segments[i] !== template.segments[i]) return null;
    }
    const value = decodePart(segments[template.idIndex]);
    return RESERVED_URL_IDS.includes(value) ? null : value;
  }
  if (
    segments.length !== template.segments.length ||
    segments.some((segment, i) => segment !== template.segments[i])
  ) {
    return null;
  }
  if (!template.paramSource) return null;
  const params =
    template.paramSource === "query"
      ? url.searchParams
      : new URLSearchParams(url.hash.slice(1));
  const value = params.get(template.paramKey);
  if (!value) return null;
  return template.queryNode ? hogqlFromQueryNode(value) : value;
}

export function parsePostHogObjectUrl(
  href: string | undefined,
  context: PostHogLinkContext | null,
): PostHogObjectUrlRef | null {
  if (!href || !context) return null;
  let url: URL;
  let base: URL;
  try {
    url = new URL(href.trim());
    base = new URL(context.appUrl);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  if (appHost(url.host) !== appHost(base.host)) return null;
  let segments = pathSegments(url.pathname);
  if (segments[0] === "project") {
    if (segments[1] !== String(context.projectId)) return null;
    segments = segments.slice(2);
  }
  for (const template of URL_TEMPLATES) {
    let value = matchTemplate(template, segments, url);
    if (value && template.idIsBody && value.trimStart().startsWith("{")) {
      value = hogqlFromQueryNode(value);
    }
    const id = value?.trim();
    if (!id) continue;
    if (template.guard && !template.guard.test(id)) continue;
    return { kind: template.kind, id, href: url.toString() };
  }
  return null;
}
