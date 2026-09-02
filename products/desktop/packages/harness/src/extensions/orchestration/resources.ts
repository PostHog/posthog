import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

export function resolveOrchestrationResource(relativePath: string): string {
  const candidates = [
    new URL(relativePath, import.meta.url),
    new URL(`./orchestration/${relativePath}`, import.meta.url),
    new URL(`./extensions/orchestration/${relativePath}`, import.meta.url),
  ].map((url) => fileURLToPath(url));
  return candidates.find(existsSync) ?? candidates[0];
}
