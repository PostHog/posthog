import { PluginEvent, PluginInput, PluginMeta } from "@posthog/plugin-scaffold";

function normalizeUrl(url: string): string {
  try {
    const parsedUrl = new URL(url.toLocaleLowerCase());
    parsedUrl.pathname = parsedUrl.pathname.replace(/\/$/, "");

    return parsedUrl.toString();
  } catch (err) {
    throw `Unable to normalize invalid URL: "${url}"`;
  }
}

export function processEvent(
  event: PluginEvent,
  meta: PluginMeta<PluginInput>
) {
  const $current_url = event?.properties?.$current_url;
  if (event?.properties && $current_url) {
    const normalized_url = normalizeUrl($current_url);
    event.properties.$current_url = normalized_url;

    console.debug(
      `event.$current_url: "${$current_url}" normalized to "${normalized_url}"`
    );
  }

  return event;
}
