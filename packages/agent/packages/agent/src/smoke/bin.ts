#!/usr/bin/env node
import { Command, Option } from "commander";
import { DEFAULT_CODEX_MODEL, DEFAULT_GATEWAY_MODEL } from "../gateway-models";
import { buildGatewayEnv } from "../server/gateway-env";
import { Logger } from "../utils/logger";
import { redactSecrets } from "../utils/redact-secrets";
import { classifyFailure, classifyOutcome, type SmokeResult } from "./classify";
import { runTurn } from "./run-turn";

const EXIT_CODES: Record<SmokeResult, number> = {
  pass: 0,
  broken: 1,
  inconclusive: 2,
  infra: 3,
};

const program = new Command()
  .name("agent-smoke")
  .description(
    "Drive one agent turn through the Go ai-gateway and report the result as one JSON line",
  )
  .addOption(
    new Option("--runtime <runtime>", "runtime adapter to drive")
      .choices(["claude", "codex"])
      .makeOptionMandatory(),
  )
  .option("--timeout <seconds>", "turn timeout in seconds", "300")
  .parse();

const { runtime, timeout } = program.opts<{
  runtime: "claude" | "codex";
  timeout: string;
}>();
delete process.env.CLAUDE_CODE_USE_BEDROCK;
const token = process.env.AI_GATEWAY_TOKEN?.trim() ?? "";
const model =
  process.env.POSTHOG_CODE_MODEL ||
  (runtime === "codex" ? DEFAULT_CODEX_MODEL : DEFAULT_GATEWAY_MODEL);
const logger = new Logger({
  debug: true,
  prefix: "[agent-smoke]",
  onLog: (level, _scope, message, data) =>
    process.stderr.write(
      `[${level}] ${message} ${data === undefined ? "" : JSON.stringify(data)}\n`,
    ),
});
const gatewayEnv = buildGatewayEnv(
  {
    apiKey: "",
    apiUrl: process.env.POSTHOG_API_URL || "https://us.posthog.com",
    projectId: Number(process.env.POSTHOG_PROJECT_ID) || 0,
  },
  { runtimeAdapter: runtime },
  logger,
);

function report(result: SmokeResult, fields: Record<string, unknown>): never {
  const line = JSON.stringify({
    runtime,
    model,
    gateway: gatewayEnv.anthropicBaseUrl,
    result,
    ...fields,
  });
  process.stdout.write(
    `${token ? redactSecrets(line).replaceAll(token, "[REDACTED]") : line}\n`,
  );
  process.exit(EXIT_CODES[result]);
}

if (!token || gatewayEnv.anthropicAuthToken !== token) {
  report("infra", {
    error:
      "the agent did not route to the Go gateway: set AI_GATEWAY_URL, AI_GATEWAY_TOKEN, AI_GATEWAY_PRODUCT and AI_GATEWAY_PRODUCTS",
  });
}

try {
  const outcome = await runTurn({
    runtime,
    model,
    gatewayEnv,
    timeoutSeconds: Number(timeout),
    logger,
  });
  const result = classifyOutcome(outcome);
  report(result, {
    stop_reason: outcome.stopReason,
    tool_calls: outcome.completedToolCalls,
    reply_has_nonce: outcome.replyHasNonce,
    ...(result !== "pass" && { reply: outcome.reply.slice(0, 2000) }),
  });
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  report(classifyFailure(message), { error: message.slice(0, 2000) });
}
