import moduleHosts from "./moduleHosts.json";

export const SKETCHPAD_MODULE_SCHEME = "posthog-sketchpad";

export const SKETCHPAD_TASK_ORIGIN = "sketchpad";

export const SKETCHPAD_MODULE_BASE = `${SKETCHPAD_MODULE_SCHEME}://`;

export const SKETCHPAD_MODULE_HOSTS = moduleHosts;
export const SKETCHPAD_ESM_HOST = moduleHosts.esm;
export const SKETCHPAD_JSDELIVR_HOST = moduleHosts.cdn;
export const SKETCHPAD_TAILWIND_PREFIX = `${SKETCHPAD_JSDELIVR_HOST}/npm/@tailwindcss/`;

export function sketchpadModuleKey(value: string): string {
  const url = new URL(value);
  const key =
    url.protocol === `${SKETCHPAD_MODULE_SCHEME}:`
      ? url.hostname
      : Object.entries(SKETCHPAD_MODULE_HOSTS).find(
          ([, host]) => host === url.origin,
        )?.[0];
  if (!key || !(key in SKETCHPAD_MODULE_HOSTS))
    throw new Error("Unsupported sketchpad module host");
  return `${key}|${url.pathname}${url.search}`;
}

export function vendoredModuleUrl(value: string): string {
  const url = new URL(value);
  const host = Object.entries(SKETCHPAD_MODULE_HOSTS).find(
    ([, origin]) => origin === url.origin,
  )?.[0];
  return host
    ? `${SKETCHPAD_MODULE_BASE}${host}${url.pathname}${url.search}`
    : value;
}
