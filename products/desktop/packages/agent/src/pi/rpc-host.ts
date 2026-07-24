import { readFileSync } from "node:fs";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { createHarnessRuntime, runRpcMode } from "@posthog/harness";
import type { PosthogProviderOptions } from "@posthog/harness/extensions/posthog-provider/provider";
import { sanitizePiHostEnvironment } from "./rpc-environment";

interface PiRpcBootstrap {
  providerOptions?: PosthogProviderOptions;
}

function argumentValue(name: string): string | undefined {
  const index = process.argv.indexOf(name);
  return index === -1 ? undefined : process.argv[index + 1];
}

const bootstrap = JSON.parse(readFileSync(3, "utf8")) as PiRpcBootstrap;
const providerOptions = bootstrap.providerOptions;
if (!providerOptions?.apiKey) {
  throw new Error("Pi RPC host requires PostHog provider credentials");
}
sanitizePiHostEnvironment();

const cwd = process.cwd();
const sessionFile = argumentValue("--session-file");
const sessionManager = sessionFile
  ? SessionManager.open(sessionFile, undefined, cwd)
  : undefined;
const runtime = await createHarnessRuntime({
  cwd,
  sessionManager,
  ...providerOptions,
});

const requestedModel = argumentValue("--model")?.replace(/^posthog\//, "");
if (requestedModel) {
  const model = runtime.services.modelRegistry.find("posthog", requestedModel);
  if (!model) {
    throw new Error(`PostHog model not found: ${requestedModel}`);
  }
  await runtime.session.setModel(model);
}

await runRpcMode(runtime);
