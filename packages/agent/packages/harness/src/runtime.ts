import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  type Credential,
  type CredentialStore,
  InMemoryCredentialStore,
} from "@earendil-works/pi-ai";
import type {
  AgentSessionRuntime,
  CreateAgentSessionFromServicesOptions,
  CreateAgentSessionRuntimeFactory,
  CreateAgentSessionServicesOptions,
} from "@earendil-works/pi-coding-agent";
import { installHogBrandEnv } from "./extensions/hog-branding/brand-env";
import {
  POSTHOG_PROVIDER_NAME,
  type PosthogOAuthCredentials,
  setPosthogOAuthCredentials,
} from "./extensions/posthog-provider/provider";
import type { HarnessExtensionOptions } from "./extensions/registry";

type PiRuntimeTarget = Parameters<CreateAgentSessionRuntimeFactory>[0];
type CredentialSnapshot = Record<string, Credential>;

function loadCredentialSnapshot(authPath: string): CredentialSnapshot {
  try {
    return JSON.parse(readFileSync(authPath, "utf8")) as CredentialSnapshot;
  } catch {
    return {};
  }
}

async function createCredentialStore(
  snapshot: CredentialSnapshot,
): Promise<CredentialStore> {
  const store = new InMemoryCredentialStore();
  for (const [providerId, credential] of Object.entries(snapshot)) {
    await store.modify(providerId, async () => credential);
  }
  return store;
}

export type HarnessRuntimeOptions = HarnessExtensionOptions & {
  credentialStore?: CredentialStore;
  posthogOAuthCredentials?: PosthogOAuthCredentials;
  projectTrusted?: (cwd: string) => boolean;
} & Partial<
    Pick<
      PiRuntimeTarget,
      "cwd" | "agentDir" | "sessionManager" | "sessionStartEvent"
    >
  > &
  Omit<CreateAgentSessionServicesOptions, "cwd" | "agentDir"> &
  Omit<
    CreateAgentSessionFromServicesOptions,
    "services" | "sessionManager" | "sessionStartEvent"
  >;

/**
 * Build the standard PostHog distribution of Pi.
 *
 * The returned value is Pi's native `AgentSessionRuntime`, so it can be
 * passed directly to `runRpcMode`, `runPrintMode`, or `InteractiveMode`, or
 * used in-process through `runtime.session`. The same factory is retained by
 * Pi and recreates all cwd-bound services and harness extensions when a
 * session is replaced, forked, or imported.
 */
export async function createHarnessRuntime(
  options: HarnessRuntimeOptions = {},
): Promise<AgentSessionRuntime> {
  const {
    credentialStore,
    posthogOAuthCredentials,
    runtimeMcpServers: _runtimeMcpServers,
    mcpToolPolicies: _mcpToolPolicies,
    requestMcpToolPermission: _requestMcpToolPermission,
    projectTrusted,
    ...runtimeOptions
  } = options;
  // Pi reads its application branding when the SDK is first evaluated. Keep
  // every runtime import below dynamic so this always happens first.
  installHogBrandEnv();

  const pi = await import("@earendil-works/pi-coding-agent");
  const [{ harnessExtensions }, { DEFAULT_MODEL }] = await Promise.all([
    import("./extensions/registry"),
    import("./extensions/posthog-provider/models"),
  ]);

  const cwd = runtimeOptions.cwd ?? process.cwd();
  const agentDir = runtimeOptions.agentDir ?? pi.getAgentDir();

  const createRuntime: CreateAgentSessionRuntimeFactory = async ({
    cwd: runtimeCwd,
    agentDir: runtimeAgentDir,
    sessionManager,
    sessionStartEvent,
  }) => {
    const authPath = join(runtimeAgentDir, "auth.json");
    const credentials =
      credentialStore ??
      (posthogOAuthCredentials
        ? await createCredentialStore(loadCredentialSnapshot(authPath))
        : undefined);
    if (credentials && posthogOAuthCredentials) {
      await setPosthogOAuthCredentials(credentials, posthogOAuthCredentials);
    }
    const modelRuntime =
      runtimeOptions.modelRuntime ??
      (await pi.ModelRuntime.create({
        authPath,
        credentials,
      }));

    const services = await pi.createAgentSessionServices({
      ...runtimeOptions,
      cwd: runtimeCwd,
      agentDir: runtimeAgentDir,
      modelRuntime,
      settingsManager:
        options.settingsManager ??
        pi.SettingsManager.create(runtimeCwd, runtimeAgentDir, {
          projectTrusted: projectTrusted?.(runtimeCwd) ?? false,
        }),
      resourceLoaderOptions: {
        ...runtimeOptions.resourceLoaderOptions,
        extensionFactories: [
          ...(runtimeOptions.resourceLoaderOptions?.extensionFactories ?? []),
          ...harnessExtensions(options),
        ],
      },
    });

    if (options.apiKey) {
      await services.modelRuntime.setRuntimeApiKey(
        POSTHOG_PROVIDER_NAME,
        options.apiKey,
      );
    }

    const preferredModel = services.modelRuntime.getModel(
      POSTHOG_PROVIDER_NAME,
      DEFAULT_MODEL,
    );
    const fallbackModel = services.modelRuntime
      .getModels(POSTHOG_PROVIDER_NAME)
      .at(0);
    const existingSession = sessionManager.buildSessionContext();
    const hasRestorableModel =
      existingSession.messages.length > 0 && existingSession.model !== null;
    const defaultModel = hasRestorableModel
      ? undefined
      : (preferredModel ?? fallbackModel);

    const created = await pi.createAgentSessionFromServices({
      ...runtimeOptions,
      services,
      sessionManager,
      sessionStartEvent,
      model: runtimeOptions.model ?? defaultModel,
    });

    return {
      ...created,
      services,
      diagnostics: [
        ...services.diagnostics,
        ...services.resourceLoader
          .getExtensions()
          .errors.map(({ path, error }) => ({
            type: "error" as const,
            message: `Failed to load extension "${path}": ${error}`,
          })),
      ],
    };
  };

  const sessionManager =
    runtimeOptions.sessionManager ?? pi.SessionManager.create(cwd);

  return pi.createAgentSessionRuntime(createRuntime, {
    cwd: sessionManager.getCwd(),
    agentDir,
    sessionManager,
    sessionStartEvent: runtimeOptions.sessionStartEvent,
  });
}
