import type {
  SketchpadCapabilities,
  SketchpadDataMethod,
} from "@posthog/shared";

const STATE_METHODS = new Set<SketchpadDataMethod>([
  "stateGet",
  "stateSet",
  "stateList",
  "stateEditText",
  "stateEditList",
]);

/** Holds a fragment to the ph.* surface it declared, the way a canvas is held
 * to its manifest. An undeclared call is refused rather than served. */
export function assertSketchpadCapability(
  capabilities: SketchpadCapabilities | undefined,
  method: SketchpadDataMethod,
  payload: unknown,
): void {
  // Board layout is the fragment's own arrangement, not a data reach, so it
  // needs no declaration.
  if (method === "arrangeFragments") return;
  if (!capabilities) {
    throw new Error(
      `This card does not declare that it uses ph.${method}. Add it to the card's capabilities to run it.`,
    );
  }
  if (method === "query") {
    if (!capabilities.inlineQueries) {
      throw new Error("This card does not declare that it runs queries.");
    }
    return;
  }
  if (method === "loadInsight") {
    const shortId = (payload as { shortId?: string })?.shortId;
    if (!shortId || !capabilities.insights.includes(shortId)) {
      throw new Error(
        `This card does not declare the insight "${shortId ?? ""}".`,
      );
    }
    return;
  }
  if (STATE_METHODS.has(method)) {
    if (!capabilities.state.includes("shared")) {
      throw new Error("This card does not declare that it uses shared state.");
    }
    return;
  }
  throw new Error(`ph.${method} is not available on sketchpads.`);
}
