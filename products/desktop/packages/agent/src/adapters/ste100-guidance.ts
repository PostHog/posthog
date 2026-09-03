import { SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION } from "@posthog/shared/product-engineer-prompt";
import { isBenjaminEnabled } from "./benjamin-guidance";

export { SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION };

type SystemPrompt = string | { append: string };

export function appendSte100Guidance(
  prompt: SystemPrompt,
  env: NodeJS.ProcessEnv = process.env,
): SystemPrompt {
  if (!isBenjaminEnabled(env)) return prompt;

  const instructions = typeof prompt === "string" ? prompt : prompt.append;
  const combined = [instructions, SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION]
    .filter(Boolean)
    .join("\n\n");

  return typeof prompt === "string" ? combined : { append: combined };
}
