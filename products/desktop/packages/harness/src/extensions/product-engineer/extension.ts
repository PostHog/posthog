import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type {
  ExtensionAPI,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import { prependProductEngineerPrompt } from "@posthog/shared/product-engineer-prompt";

function resolveProductEngineerResource(relativePath: string): string {
  const adjacentPath = fileURLToPath(new URL(relativePath, import.meta.url));
  if (existsSync(adjacentPath)) {
    return adjacentPath;
  }
  return fileURLToPath(
    new URL(`./product-engineer/${relativePath}`, import.meta.url),
  );
}

export function createProductEngineerExtension(
  instrumentationSkillsDirectory = resolveProductEngineerResource("skills"),
): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    pi.on("resources_discover", () => ({
      skillPaths: existsSync(instrumentationSkillsDirectory)
        ? [instrumentationSkillsDirectory]
        : [],
    }));
    pi.on("before_agent_start", (event) => ({
      systemPrompt: prependProductEngineerPrompt(event.systemPrompt),
    }));
  };
}

export default createProductEngineerExtension();
