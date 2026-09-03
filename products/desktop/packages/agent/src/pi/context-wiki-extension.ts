import * as fs from "node:fs";
import type {
  ExtensionFactory,
  InlineExtension,
} from "@earendil-works/pi-coding-agent";
import { buildContextWikiInstructions } from "../context-wiki";

type NamedInlineExtension = Exclude<InlineExtension, ExtensionFactory>;

/**
 * Appends the org's context-wiki instructions to Pi's system prompt. The mount
 * path arrives via the rpc bootstrap; the extension no-ops when no wiki is
 * mounted, so callers can always register it.
 */
export function createPiContextWikiExtension(
  mountPath: string | undefined,
): NamedInlineExtension {
  return {
    name: "posthog-context-wiki",
    factory: (pi) => {
      pi.on("before_agent_start", async (event) => {
        if (!mountPath || !fs.existsSync(mountPath)) {
          return {};
        }
        return {
          systemPrompt:
            event.systemPrompt + buildContextWikiInstructions(mountPath),
        };
      });
    },
  };
}
