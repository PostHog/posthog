import { readFileSync } from "node:fs";
import {
  type InlineExtension,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { createHarnessRuntime, runRpcMode } from "@posthog/harness";
import { createAutoPublishExtension } from "@posthog/harness/extensions/auto-publish";
import { createPiRuntimeTrustResolver } from "@posthog/harness/project-trust";
import type {
  McpToolPermissionDecision,
  McpToolPermissionRequest,
} from "@posthog/shared";
import { createPiContextWikiExtension } from "./context-wiki-extension";
import { createPiEnrichmentExtension } from "./enrichment-extension";
import {
  POSTHOG_PI_QUEUE_ENTRY_TYPE,
  readPersistedPiQueue,
} from "./queue-persistence";
import { createPiRepositoryToolsExtension } from "./repository-tools-extension";
import type { PiRpcBootstrap, PiRuntimeExtension } from "./rpc-client";
import { sanitizePiHostEnvironment } from "./rpc-environment";

interface PiHostRequest {
  type: "posthog_pi_host_request";
  id: string;
  method: "get_queue" | "clear_queue";
}

function argumentValue(name: string): string | undefined {
  const index = process.argv.indexOf(name);
  return index === -1 ? undefined : process.argv[index + 1];
}

const bootstrap = JSON.parse(
  readFileSync(3, "utf8"),
) as Partial<PiRpcBootstrap>;
const providerOptions = bootstrap.providerOptions;
if (!providerOptions?.apiKey) {
  throw new Error("Pi RPC host requires PostHog provider credentials");
}
sanitizePiHostEnvironment();

const cwd = process.cwd();
const sessionFile = argumentValue("--session-file");
const sessionManager = sessionFile
  ? SessionManager.open(sessionFile, undefined, cwd)
  : SessionManager.create(cwd);
function requestMcpToolPermission(
  request: McpToolPermissionRequest,
): Promise<McpToolPermissionDecision> {
  return new Promise((resolve) => {
    const onMessage = (message: unknown) => {
      const response = message as {
        type?: string;
        requestId?: string;
        decision?: McpToolPermissionDecision;
      };
      if (
        response.type !== "posthog_pi_mcp_permission_response" ||
        response.requestId !== request.requestId ||
        !response.decision
      ) {
        return;
      }
      process.off("message", onMessage);
      resolve(response.decision);
    };
    process.on("message", onMessage);
    process.send?.({ type: "posthog_pi_mcp_permission_request", request });
  });
}

const extensionFactories: Record<PiRuntimeExtension, InlineExtension> = {
  "repository-tools": createPiRepositoryToolsExtension(cwd),
  "auto-publish": {
    name: "posthog-auto-publish",
    factory: createAutoPublishExtension(),
  },
  "context-wiki": createPiContextWikiExtension(bootstrap.contextWikiPath),
};
const runtimeExtensions = (bootstrap.extensions ?? []).map(
  (extension) => extensionFactories[extension],
);
if (bootstrap.enrichment) {
  runtimeExtensions.push(createPiEnrichmentExtension(bootstrap.enrichment));
}

const runtime = await createHarnessRuntime({
  cwd,
  sessionManager,
  projectTrusted: createPiRuntimeTrustResolver(
    cwd,
    bootstrap.projectTrusted ?? false,
  ),
  resourceLoaderOptions: { extensionFactories: runtimeExtensions },
  ...providerOptions,
  runtimeMcpServers: bootstrap.runtimeMcpServers,
  mcpToolPolicies: bootstrap.mcpToolPolicies,
  requestMcpToolPermission,
});

const persistedQueue = readPersistedPiQueue(sessionManager.getEntries());
for (const message of persistedQueue.steering) {
  await runtime.session.steer(message);
}
for (const message of persistedQueue.followUp) {
  await runtime.session.followUp(message);
}
runtime.session.subscribe((event) => {
  if (event.type !== "queue_update") {
    return;
  }
  runtime.session.sessionManager.appendCustomEntry(
    POSTHOG_PI_QUEUE_ENTRY_TYPE,
    {
      steering: [...event.steering],
      followUp: [...event.followUp],
    },
  );
});

const requestedModel = argumentValue("--model")?.replace(/^posthog\//, "");
if (requestedModel) {
  const model = runtime.services.modelRuntime.getModel(
    "posthog",
    requestedModel,
  );
  if (!model) {
    throw new Error(`PostHog model not found: ${requestedModel}`);
  }
  await runtime.session.setModel(model);
}

process.on("message", (message: unknown) => {
  const request = message as Partial<PiHostRequest>;
  if (
    request.type !== "posthog_pi_host_request" ||
    typeof request.id !== "string" ||
    (request.method !== "get_queue" && request.method !== "clear_queue")
  ) {
    return;
  }

  try {
    const session = runtime.session;
    const data =
      request.method === "clear_queue"
        ? session.clearQueue()
        : {
            steering: [...session.getSteeringMessages()],
            followUp: [...session.getFollowUpMessages()],
          };
    process.send?.({
      type: "posthog_pi_host_response",
      id: request.id,
      data,
    });
  } catch (error) {
    process.send?.({
      type: "posthog_pi_host_response",
      id: request.id,
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

await runRpcMode(runtime);
