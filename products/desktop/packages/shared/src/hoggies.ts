import * as hoggiePngs from "@posthog/brand/hoggies/png";

/**
 * Slugs and export names disagree on punctuation and capitals: the file
 * `dadd-ai-1.png` is exported as `hedgehogDaddAI1Png`, and `9-9-6.png` as
 * `hedgehog996Png`. Stripping everything but letters and digits makes both
 * sides meet, and it accepts a slug in either spelling.
 */
function normalize(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/**
 * Every hoggie PNG of the installed PostHog/brand release, keyed by normalized
 * file name. The whole set is bundled, so a hoggie renders with no network.
 */
const HOGGIE_PNG: Record<string, string> = Object.fromEntries(
  Object.entries(hoggiePngs)
    .filter(
      (entry): entry is [string, string] =>
        /^hedgehog.*Png$/.test(entry[0]) && typeof entry[1] === "string",
    )
    .map(([name, src]) => [
      normalize(name.replace(/^hedgehog/, "").replace(/Png$/, "")),
      src,
    ]),
);

/** The bundled PNG for a hoggie file name, or undefined for an unknown one. */
export function hoggiePng(slug: string): string | undefined {
  return HOGGIE_PNG[normalize(slug)];
}
