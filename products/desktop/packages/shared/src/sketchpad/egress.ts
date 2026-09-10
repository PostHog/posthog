export const SKETCHPAD_MODULE_SCHEME = "posthog-sketchpad";

export const SKETCHPAD_TASK_ORIGIN = "sketchpad";

export const SKETCHPAD_MODULE_BASE = `${SKETCHPAD_MODULE_SCHEME}://`;

export const SKETCHPAD_ESM_HOST = "https://esm.sh";
export const SKETCHPAD_JSDELIVR_HOST = "https://cdn.jsdelivr.net";
export const SKETCHPAD_TAILWIND_PREFIX = `${SKETCHPAD_JSDELIVR_HOST}/npm/@tailwindcss/`;

export const SKETCHPAD_MODULE_URL_PREFIXES: readonly string[] = [
  `${SKETCHPAD_ESM_HOST}/`,
  SKETCHPAD_TAILWIND_PREFIX,
];

export function isSketchpadModuleUrl(url: string): boolean {
  return SKETCHPAD_MODULE_URL_PREFIXES.some((prefix) => url.startsWith(prefix));
}

export function vendoredModuleUrl(url: string): string {
  if (url.startsWith(`${SKETCHPAD_ESM_HOST}/`)) {
    return `${SKETCHPAD_MODULE_BASE}esm${url.slice(SKETCHPAD_ESM_HOST.length)}`;
  }
  if (url.startsWith(SKETCHPAD_JSDELIVR_HOST)) {
    return `${SKETCHPAD_MODULE_BASE}cdn${url.slice(SKETCHPAD_JSDELIVR_HOST.length)}`;
  }
  return url;
}
