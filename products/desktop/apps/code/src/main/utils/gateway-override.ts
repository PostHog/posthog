import type {
  GatewayTokenHost,
  GatewayTokenOverride,
} from "@posthog/core/llm-gateway/identifiers";
import { validateAiGatewayUrl } from "@posthog/shared";

const URL_VAR = "POSTHOG_CODE_AI_GATEWAY_URL";
const TOKEN_VAR = "POSTHOG_CODE_AI_GATEWAY_TOKEN";

/**
 * Reads the dev Go gateway override once and deletes it from the env, since
 * every child process (the Claude CLI included) inherits the whole env.
 */
export function takeGatewayOverride(
  env: NodeJS.ProcessEnv = process.env,
): GatewayTokenOverride | null {
  const rawUrl = env[URL_VAR];
  const token = env[TOKEN_VAR];
  delete env[URL_VAR];
  delete env[TOKEN_VAR];
  if (!rawUrl || !token) return null;
  const url = rawUrl.trim().replace(/\/v1\/?$/, "");
  const origin = validateAiGatewayUrl(url, { allowLoopback: true });
  return origin ? { url: origin, token } : null;
}

export function desktopGatewayTokenHost(
  env: NodeJS.ProcessEnv = process.env,
): GatewayTokenHost {
  return { goEnabled: true, override: takeGatewayOverride(env) };
}
