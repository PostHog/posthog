import type {
  ExtensionAPI,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import { SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION } from "@posthog/shared/product-engineer-prompt";
import { BENJAMIN_INSTRUCTION } from "./benjamin/instruction";

export {
  BENJAMIN_INSTRUCTION,
  BENJAMIN_UPSTREAM_COMMIT,
} from "./benjamin/instruction";
export { SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION };

type SystemPrompt = string | { append: string };

const BENJAMIN_GUIDANCE = BENJAMIN_INSTRUCTION.trim();

export function isBenjaminEnabled(
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const value = env.POSTHOG_BENJAMIN?.trim().toLowerCase();
  return value === "1" || value === "true";
}

export function appendBenjaminGuidance(
  instructions: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  if (!isBenjaminEnabled(env)) return instructions;
  return [instructions, BENJAMIN_GUIDANCE].filter(Boolean).join("\n\n");
}

export function appendSte100Guidance<T extends SystemPrompt>(
  prompt: T,
  env: NodeJS.ProcessEnv = process.env,
): T {
  if (!isBenjaminEnabled(env)) return prompt;

  const instructions = typeof prompt === "string" ? prompt : prompt.append;
  const combined = [instructions, SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION]
    .filter(Boolean)
    .join("\n\n");

  return (typeof prompt === "string" ? combined : { append: combined }) as T;
}

export function createBenjaminGuidanceExtension(): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    pi.on("before_agent_start", (event) => ({
      systemPrompt: appendSte100Guidance(
        appendBenjaminGuidance(event.systemPrompt),
      ),
    }));
  };
}

export default function benjaminGuidance(
  pi: ExtensionAPI,
): void | Promise<void> {
  return createBenjaminGuidanceExtension()(pi);
}
