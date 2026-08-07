import { DEFAULT_GATEWAY_MODEL } from "@posthog/agent/gateway-models";
import { getIsOnline } from "@posthog/core/connectivity/connectivityStore";
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
import { SPOKEN_NARRATION_FLAG } from "@posthog/shared";
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
import { NotificationBus } from "@posthog/ui/features/notifications/notifications";
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
    notifyPermissionRequest: (taskTitle, taskId) =>
      resolveService(NotificationBus).notifyPermissionRequest(
        taskTitle,
        taskId,
      ),
    notifyPromptComplete: (taskTitle, stopReason, taskId, durationMs) =>
      resolveService(NotificationBus).notifyPromptComplete(
        taskTitle,
        stopReason,
        taskId,
        durationMs,
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
