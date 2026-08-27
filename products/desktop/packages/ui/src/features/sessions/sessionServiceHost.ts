import { DEFAULT_GATEWAY_MODEL } from "@posthog/agent/gateway-models";
import { getIsOnline } from "@posthog/core/connectivity/connectivityStore";
import {
  AGENT_SESSION_NOTIFIER,
  type AgentSessionNotifier,
} from "@posthog/core/notification/agentSessionNotifications";
import { CloudArtifactService } from "@posthog/core/sessions/cloudArtifactService";
import {
  combineQueuedCloudPrompts,
  getCloudPromptTransport,
} from "@posthog/core/sessions/cloudPrompt";
import {
  SessionService,
  type SessionServiceDeps,
} from "@posthog/core/sessions/sessionService";
import { extractSkillButtonId } from "@posthog/core/skill-buttons/prompts";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import {
  BEDROCK_GATEWAY_VARIANTS,
  BEDROCK_LLM_GATEWAY_FLAG,
  type BedrockGatewayVariant,
  SPOKEN_NARRATION_FLAG,
} from "@posthog/shared";
import {
  createAuthenticatedClient,
  getAuthenticatedClient,
} from "@posthog/ui/features/auth/authClientImperative";
import { fetchAuthState } from "@posthog/ui/features/auth/authQueries";
import { useUsageLimitStore } from "@posthog/ui/features/billing/usageLimitStore";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import { useAddDirectoryDialogStore } from "@posthog/ui/features/folder-picker/addDirectoryDialogStore";
import { SpeechNotifier } from "@posthog/ui/features/notifications/speechNotifier";
import { useSessionAdapterStore } from "@posthog/ui/features/sessions/sessionAdapterStore";
import {
  getPersistedConfigOptions,
  removePersistedConfigOptions,
  setPersistedConfigOptions,
} from "@posthog/ui/features/sessions/sessionConfigStore";
import { sessionStoreSetters } from "@posthog/ui/features/sessions/sessionStore";
import {
  getEffectiveCustomInstructions,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { taskViewedApi } from "@posthog/ui/features/sidebar/taskMetaApi";
import { WORKSPACE_QUERY_KEY } from "@posthog/ui/features/workspace/identifiers";
import { toast } from "@posthog/ui/primitives/toast";
import {
  buildPermissionToolMetadata,
  track,
} from "@posthog/ui/shell/posthogAnalyticsImpl";
import { logger } from "../../shell/logger";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "../../shell/queryClient";
import { resolveLocalSkillPrompt } from "../message-editor/commands";

export { SessionService };

const log = logger.scope("session-service");

export function shouldEnableSpokenNarration(
  userOptedIn: boolean,
  flagEnabled: boolean,
  isDevelopment: boolean,
): boolean {
  return userOptedIn && (flagEnabled || isDevelopment);
}

/**
 * Narrow the raw flag value to a known variant. An unmatched flag, an
 * unresolved one, or a variant added in PostHog that this build does not know
 * about all yield undefined, which leaves the session on the gateway's default
 * provider rather than guessing.
 *
 * posthog-js resolves flags asynchronously, so a session started before the
 * first load finishes reads undefined and runs on Anthropic. That window is
 * effectively the first launch after install, because posthog-js restores
 * cached flags from its persistence layer on init, and this flag matches on
 * `email`, which only exists once `identify` runs.
 *
 * An unresolved variant is deliberately not treated as `control`: the session
 * sends no `$feature/` property at all, so it drops out of both arms instead of
 * inflating control. That keeps the comparison honest at the cost of losing a
 * few early sessions. Waiting for flags here would put a network round trip in
 * front of every session start and reconnect, which is a worse trade.
 */
export function resolveBedrockGatewayVariant(
  rawVariant: string | undefined,
): BedrockGatewayVariant | undefined {
  return BEDROCK_GATEWAY_VARIANTS.find((variant) => variant === rawVariant);
}

function hostClient(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

function buildSessionServiceDeps(): SessionServiceDeps {
  const trpc = hostClient();
  const queryClient = resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  );
  const cloudArtifactService = new CloudArtifactService(
    (filePath) => trpc.fs.readFileAsBase64.query({ filePath }),
    (skillBundleRef) => trpc.skills.bundleLocal.query(skillBundleRef),
    (skillBundleRefs) => trpc.skills.resolveDependencies.query(skillBundleRefs),
  );

  return {
    trpc,
    store: sessionStoreSetters,
    log,
    toast: {
      error: (msg, opts) => toast.error(msg, opts),
      info: (msg, opts) => toast.info(msg, opts),
    },
    track: (event, props) => {
      (track as (event: string, props?: Record<string, unknown>) => void)(
        event,
        props,
      );
    },
    buildPermissionToolMetadata,
    notifyAgentSession: (notification) =>
      resolveService<AgentSessionNotifier>(AGENT_SESSION_NOTIFIER).notify(
        notification,
      ),
    enqueueSpeech: (request) => resolveService(SpeechNotifier).speak(request),
    getIsOnline,
    fetchAuthState,
    getAuthenticatedClient,
    createAuthenticatedClient,
    getPersistedConfigOptions: (taskRunId) =>
      getPersistedConfigOptions(taskRunId) ?? undefined,
    setPersistedConfigOptions,
    removePersistedConfigOptions,
    adapterStore: {
      getAdapter: (taskRunId) =>
        useSessionAdapterStore.getState().getAdapter(taskRunId),
      setAdapter: (taskRunId, adapter) =>
        useSessionAdapterStore.getState().setAdapter(taskRunId, adapter),
      removeAdapter: (taskRunId) =>
        useSessionAdapterStore.getState().removeAdapter(taskRunId),
    },
    get settings() {
      const state = useSettingsStore.getState();
      return {
        ...state,
        customInstructions: getEffectiveCustomInstructions(state),
        spokenNarrationEnabled: shouldEnableSpokenNarration(
          state.spokenNotifications,
          resolveService<FeatureFlags>(FEATURE_FLAGS).isEnabled(
            SPOKEN_NARRATION_FLAG,
          ),
          import.meta.env.DEV,
        ),
        bedrockGatewayVariant: resolveBedrockGatewayVariant(
          resolveService<FeatureFlags>(FEATURE_FLAGS).getVariant(
            BEDROCK_LLM_GATEWAY_FLAG,
          ),
        ),
      };
    },
    usageLimit: {
      show: (...args) => useUsageLimitStore.getState().show(...args),
    },
    get addDirectoryDialog() {
      return { open: useAddDirectoryDialogStore.getState().open };
    },
    taskViewedApi: {
      markActivity: (taskId) => taskViewedApi.markActivity(taskId),
    },
    queryClient,
    DEFAULT_GATEWAY_MODEL,
    WORKSPACE_QUERY_KEY,
    h: {
      extractSkillButtonId,
      combineQueuedCloudPrompts,
      getCloudPromptTransport,
      resolveLocalSkillCommandPrompt: (prompt) =>
        resolveLocalSkillPrompt(prompt, () => trpc.skills.list.query()),
      uploadRunOutput: (client, taskId, runId, name, content, contentType) =>
        cloudArtifactService.uploadRunOutput(
          client,
          taskId,
          runId,
          name,
          content,
          contentType,
        ),
      uploadRunAttachments: (client, taskId, runId, filePaths, skillBundles) =>
        cloudArtifactService.uploadRunAttachments(
          client,
          taskId,
          runId,
          filePaths,
          skillBundles,
        ),
      uploadTaskStagedAttachments: (client, taskId, filePaths, skillBundles) =>
        cloudArtifactService.uploadTaskStagedAttachments(
          client,
          taskId,
          filePaths,
          skillBundles,
        ),
    },
  };
}

// --- Singleton Service Instance ---

let serviceInstance: SessionService | null = null;

export function getSessionService(): SessionService {
  if (!serviceInstance) {
    serviceInstance = new SessionService(buildSessionServiceDeps());
  }
  return serviceInstance;
}

export function resetSessionService(): void {
  if (serviceInstance) {
    serviceInstance.reset();
    serviceInstance = null;
  }

  sessionStoreSetters.clearAll();

  hostClient()
    .agent.resetAll.mutate()
    .catch((err) => {
      log.error("Failed to reset all sessions on main process", err);
    });
}
