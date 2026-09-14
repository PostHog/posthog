import { BENJAMIN_INSTRUCTION } from "./benjamin/instruction";

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
