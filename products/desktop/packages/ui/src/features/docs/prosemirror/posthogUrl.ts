/**
 * A PostHog link, read as the thing it points at.
 *
 * A pasted link to a task, an insight, a dashboard, a replay, or any other
 * object becomes the chip for it, so the page shows what it is instead of an
 * address. Only the path is read: the host differs per region and per dev setup.
 * A desktop route or a deep link to a task reads the same as its web address.
 */

export type PastedRef =
  | { type: "taskChip"; attrs: { taskId: string; label: string } }
  | {
      type: "objectChip";
      attrs: { kind: string; objectId: string; label: string };
    };

const ID = "([A-Za-z0-9][A-Za-z0-9_.:-]*)";

/** The object kinds by the path they live at in the PostHog app. */
const OBJECT_PATHS: [RegExp, string][] = [
  [new RegExp(`^/insights/${ID}$`), "insight"],
  [new RegExp(`^/dashboard/${ID}$`), "dashboard"],
  [new RegExp(`^/code/canvas/[^/]+/${ID}$`), "dashboard"],
  [new RegExp(`^/error_tracking/${ID}$`), "error"],
  [new RegExp(`^/replay/${ID}$`), "replay"],
  [/^\/feature_flags\/(\d+)$/, "flag"],
  [/^\/experiments\/(\d+)$/, "experiment"],
  [new RegExp(`^/surveys/${ID}$`), "survey"],
  [new RegExp(`^/support/tickets/${ID}$`), "ticket"],
  [new RegExp(`^/ai-observability/traces/${ID}$`), "trace"],
  [new RegExp(`^/ai-evals/evaluations/${ID}$`), "eval"],
  [/^\/cohorts\/(\d+)$/, "cohort"],
  [/^\/data-management\/actions\/(\d+)$/, "action"],
  [new RegExp(`^/persons?/${ID}$`), "person"],
];

const TASK_PATH = new RegExp(`^/code/channel/[^/]+/tasks/${ID}$`);

/** Words that sit where an id would, and are not one. */
const NOT_IDS = new Set(["new", "edit", "settings"]);

/** The web path an address means. A desktop route and a deep link read as the web route. */
function appPath(url: URL): string | null {
  if (url.protocol === "posthog-code:")
    return `/code/${url.host}${url.pathname}`;
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  if (url.hash.startsWith("#/spaces/"))
    return `/code/channel${url.hash.slice("#/spaces".length)}`;
  return url.pathname.replace(/^\/project\/\d+/, "").replace(/\/$/, "");
}

export function refFromUrl(text: string): PastedRef | null {
  const raw = text.trim();
  if (!raw || /\s/.test(raw)) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  const path = appPath(url);
  if (path === null) return null;

  const task = TASK_PATH.exec(path);
  if (task) return { type: "taskChip", attrs: { taskId: task[1], label: "" } };

  for (const [pattern, kind] of OBJECT_PATHS) {
    const match = pattern.exec(path);
    if (!match || NOT_IDS.has(match[1])) continue;
    return {
      type: "objectChip",
      attrs: { kind, objectId: decodeURIComponent(match[1]), label: "" },
    };
  }
  return null;
}
