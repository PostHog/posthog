export const CANVAS_V2_MODULE_SCHEME = "posthog-canvas";

/** The task origin a board's own session carries. */
export const CANVAS_TASK_ORIGIN = "canvas";

export const CANVAS_V2_MODULE_BASE = `${CANVAS_V2_MODULE_SCHEME}://`;

export const CANVAS_V2_ESM_HOST = "https://esm.sh";
export const CANVAS_V2_JSDELIVR_HOST = "https://cdn.jsdelivr.net";
export const CANVAS_V2_TAILWIND_PREFIX = `${CANVAS_V2_JSDELIVR_HOST}/npm/@tailwindcss/`;

export const CANVAS_V2_MODULE_URL_PREFIXES: readonly string[] = [
  `${CANVAS_V2_ESM_HOST}/`,
  CANVAS_V2_TAILWIND_PREFIX,
];

export function isCanvasV2ModuleUrl(url: string): boolean {
  return CANVAS_V2_MODULE_URL_PREFIXES.some((prefix) => url.startsWith(prefix));
}

export function vendoredModuleUrl(url: string): string {
  if (url.startsWith(`${CANVAS_V2_ESM_HOST}/`)) {
    return `${CANVAS_V2_MODULE_BASE}esm${url.slice(CANVAS_V2_ESM_HOST.length)}`;
  }
  if (url.startsWith(CANVAS_V2_JSDELIVR_HOST)) {
    return `${CANVAS_V2_MODULE_BASE}cdn${url.slice(CANVAS_V2_JSDELIVR_HOST.length)}`;
  }
  return url;
}
