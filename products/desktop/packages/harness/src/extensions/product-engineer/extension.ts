import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type {
  ExtensionAPI,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";

function resolveProductEngineerResource(relativePath: string): string {
  const adjacentPath = fileURLToPath(new URL(relativePath, import.meta.url));
  if (existsSync(adjacentPath)) {
    return adjacentPath;
  }
  return fileURLToPath(
    new URL(`./product-engineer/${relativePath}`, import.meta.url),
  );
}

const PRODUCT_ENGINEER_PROMPT = readFileSync(
  resolveProductEngineerResource("prompts/product-engineer.md"),
  "utf8",
).trim();

function addProductEngineerPrompt(systemPrompt: string): string {
  return systemPrompt.startsWith(PRODUCT_ENGINEER_PROMPT)
    ? systemPrompt
    : `${PRODUCT_ENGINEER_PROMPT}\n\n${systemPrompt}`;
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
      systemPrompt: addProductEngineerPrompt(event.systemPrompt),
    }));
  };
}

export default createProductEngineerExtension();
