// Desktop host service bindings live here as features move into packages.
// Importing the renderer container performs today's existing bindings.
import "@renderer/di/container";
import {
  setPosthogApiClientAppVersion,
  setPosthogApiClientLogger,
} from "@posthog/api-client/posthog-client";
import { archiveModule } from "@posthog/core/archive/archive.module";
import {
  ARCHIVE_CLIENT,
  type ArchiveClient,
} from "@posthog/core/archive/identifiers";
import {
  AUTORESEARCH_GATE,
  AUTORESEARCH_SESSION_CLIENT,
  AUTORESEARCH_STORAGE_CLIENT,
  type AutoresearchGate,
  type AutoresearchSessionClient,
  type AutoresearchStorageClient,
} from "@posthog/core/autoresearch/identifiers";
import {
  LINEAR_OAUTH_FLOW,
  type LinearOAuthFlow,
  REPORT_MODEL_RESOLVER,
  type ReportModelResolver,
} from "@posthog/core/inbox/identifiers";
import { selectModelFromOptions } from "@posthog/core/inbox/reportTaskCreation";
import {
  GITHUB_CONNECT_CLIENT as INTEGRATIONS_GITHUB_CONNECT_CLIENT,
  type GithubConnectClient as IntegrationsGithubConnectClient,
  REPOSITORIES_CLIENT,
  REPOSITORIES_SERVICE,
  type RepositoriesClient,
} from "@posthog/core/integrations/identifiers";
import { RepositoriesService } from "@posthog/core/integrations/repositoriesService";
import {
  GITHUB_CONNECT_CLIENT,
  type GithubConnectClient,
} from "@posthog/core/onboarding/identifiers";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { SETUP_STORE } from "@posthog/core/setup/identifiers";
import {
  SPEECH_SETTINGS_PROVIDER,
  SPEECH_USER_NAME_PROVIDER,
  type SpeechSettingsProvider,
  type UserNameProvider,
} from "@posthog/core/speech/identifiers";
import { resolveService } from "@posthog/di/container";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  HOST_CAPABILITIES,
  type HostCapabilities,
} from "@posthog/platform/host-capabilities";
import {
  type INotifications,
  NOTIFICATIONS_SERVICE,
  type NotificationTarget,
} from "@posthog/platform/notifications";
import { type ISpeech, SPEECH_SERVICE } from "@posthog/platform/speech";
import {
  type Adapter,
  AUTORESEARCH_FLAG,
  type CloudRegion,
} from "@posthog/shared";
import {
  AUTH_SIDE_EFFECTS,
  type IAuthSideEffects,
} from "@posthog/ui/features/auth/identifiers";
import { authKeys } from "@posthog/ui/features/auth/useCurrentUser";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import {
  FILE_WATCHER_CLIENT,
  type FileWatcherClient,
} from "@posthog/ui/features/file-watcher/identifiers";
import { GIT_CACHE_KEY_PROVIDER } from "@posthog/ui/features/git-interaction/gitCacheProvider";
import {
  UiGithubConnectClient,
  UiRepositoriesClient,
} from "@posthog/ui/features/integrations/integrationsClientImpl";
import { NAVIGATION_TASK_BINDER } from "@posthog/ui/features/navigation/taskBinder";
import { navigationTaskBinder } from "@posthog/ui/features/navigation/taskBinderImpl";
import {
  ACTIVE_VIEW_PROVIDER,
  type IActiveView,
  type INotificationSettings,
  type ISpeechNotifySettings,
  NOTIFICATION_SETTINGS_PROVIDER,
  SPEECH_NOTIFY_SETTINGS,
} from "@posthog/ui/features/notifications/identifiers";
import { OnboardingGithubConnectClient } from "@posthog/ui/features/onboarding/githubConnectClientImpl";
import {
  AGENT_PROMPT_SENDER,
  type AgentPromptSender,
} from "@posthog/ui/features/sessions/agentPromptSender";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import {
  type ISpeechKeyStore,
  SPEECH_KEY_STORE,
} from "@posthog/ui/features/settings/speechKeyStore";
import { getCurrentMatches } from "@posthog/ui/router/navigationBridge";
import { HEDGEHOG_MODE_HOST } from "@posthog/ui/shell/hedgehogModeHost";
import { posthogFeatureFlags } from "@posthog/ui/shell/posthogAnalyticsImpl";
import type { ImperativeQueryClient } from "@posthog/ui/shell/queryClient";
import { IMPERATIVE_QUERY_CLIENT } from "@posthog/ui/shell/queryClient";
import {
  FILE_PATH_RESOLVER,
  type FilePathResolver,
} from "@posthog/ui/utils/getFilePath";
import {
  isSpeechSupported,
  playAudioBase64,
  speakSystemVoice,
  stopSpeech,
} from "@posthog/ui/utils/speech";
import { ELEVENLABS_API_KEY_STORE_KEY } from "@posthog/workspace-server/services/speech/identifiers";
import { container } from "@renderer/di/container";
import { RendererAuthSideEffects } from "@renderer/platform-adapters/auth-side-effects";
import { gitCacheKeyProvider } from "@renderer/platform-adapters/git-cache-keys";
import { RendererHedgehogModeHost } from "@renderer/platform-adapters/hedgehog-mode-host";
import { setupStore } from "@renderer/platform-adapters/setup";
import { initTours } from "@renderer/platform-adapters/tour";
import { hostTrpcClient, trpcClient } from "@renderer/trpc/client";
import { logger } from "@utils/logger";
import { queryClient } from "@utils/queryClient";

container.bind(IMPERATIVE_QUERY_CLIENT).toConstantValue(queryClient);
container.bind(GIT_CACHE_KEY_PROVIDER).toConstantValue(gitCacheKeyProvider);

// archive
container.load(archiveModule);
container.bind(ARCHIVE_CLIENT).toConstantValue({
  unarchive: (input) => hostTrpcClient.archive.unarchive.mutate(input),
  delete: (input) => hostTrpcClient.archive.delete.mutate(input),
  showArchivedTaskContextMenu: (input) =>
    hostTrpcClient.contextMenu.showArchivedTaskContextMenu.mutate(input),
} satisfies ArchiveClient);

// inbox host capabilities
const reportModelResolverLog = logger.scope("report-model-resolver");
container.bind<ReportModelResolver>(REPORT_MODEL_RESOLVER).toConstantValue({
  async resolveDefaultModel(
    apiHost: string,
    adapter: Adapter,
    preferredModel?: string | null,
  ): Promise<string | undefined> {
    try {
      const options = await hostTrpcClient.agent.getPreviewConfigOptions.query({
        apiHost,
        adapter,
      });
      return selectModelFromOptions(options, preferredModel);
    } catch (error) {
      reportModelResolverLog.warn("Failed to resolve default model", {
        error,
        adapter,
      });
      return undefined;
    }
  },
});
container.bind(LINEAR_OAUTH_FLOW).toConstantValue({
  startFlow: async (region: string, projectId: number) => {
    await hostTrpcClient.linearIntegration.startFlow.mutate({
      region: region as CloudRegion,
      projectId,
    });
  },
} satisfies LinearOAuthFlow);

// onboarding
container
  .bind<GithubConnectClient>(GITHUB_CONNECT_CLIENT)
  .toConstantValue(new OnboardingGithubConnectClient());

// integrations
container
  .bind<IntegrationsGithubConnectClient>(INTEGRATIONS_GITHUB_CONNECT_CLIENT)
  .toConstantValue(new UiGithubConnectClient());
container
  .bind<RepositoriesClient>(REPOSITORIES_CLIENT)
  .toConstantValue(new UiRepositoriesClient());
container.bind(REPOSITORIES_SERVICE).to(RepositoriesService).inSingletonScope();

container
  .bind(HEDGEHOG_MODE_HOST)
  .toConstantValue(new RendererHedgehogModeHost());
container
  .bind<AgentPromptSender>(AGENT_PROMPT_SENDER)
  .toConstantValue(async (taskId, prompt) => {
    await resolveService<SessionService>(SESSION_SERVICE).sendPrompt(
      taskId,
      prompt,
    );
  });
container
  .bind<AutoresearchSessionClient>(AUTORESEARCH_SESSION_CLIENT)
  .toConstantValue({
    sendPrompt: (taskId, prompt) =>
      resolveService<SessionService>(SESSION_SERVICE).sendPrompt(
        taskId,
        prompt,
      ),
    setModel: (taskId, model) =>
      resolveService<SessionService>(
        SESSION_SERVICE,
      ).setSessionConfigOptionByCategory(taskId, "model", model),
    setEffort: (taskId, effort) =>
      resolveService<SessionService>(
        SESSION_SERVICE,
      ).setSessionConfigOptionByCategory(taskId, "thought_level", effort),
    reconnect: async (taskId) => {
      const workspaces = (await trpcClient.workspace.getAll.query()) as Record<
        string,
        { mode?: string; worktreePath?: string | null; folderPath?: string }
      >;
      const workspace = workspaces[taskId];
      // Cloud sessions are re-established by the app's own cloud-task watcher,
      // not clearSessionError (which is local-only). Leave recovery to that;
      // autoresearch resumes when the session becomes usable again.
      if (workspace?.mode === "cloud") return;
      const repoPath = workspace?.worktreePath ?? workspace?.folderPath;
      if (!repoPath) {
        throw new Error(`No workspace found for task ${taskId}`);
      }
      await resolveService<SessionService>(SESSION_SERVICE).clearSessionError(
        taskId,
        repoPath,
      );
    },
  });
container.bind<AutoresearchGate>(AUTORESEARCH_GATE).toConstantValue({
  isEnabled: () => {
    // Always on in dev builds; staff-gated via the flag in production.
    if (import.meta.env.DEV) return Promise.resolve(true);
    return new Promise<boolean>((resolve) => {
      // posthog-js may still be fetching flags at boot; onFlagsLoaded fires
      // right away (possibly synchronously) when they are already known,
      // otherwise on first load. Fall back to the current (cached) value if
      // nothing arrives in time.
      let unsubscribe: (() => void) | undefined;
      let timer: ReturnType<typeof setTimeout> | undefined;
      let settled = false;
      const settle = () => {
        if (settled) return;
        settled = true;
        unsubscribe?.();
        if (timer !== undefined) clearTimeout(timer);
        resolve(posthogFeatureFlags.isEnabled(AUTORESEARCH_FLAG));
      };
      unsubscribe = posthogFeatureFlags.onFlagsLoaded(settle);
      if (settled) {
        unsubscribe();
        return;
      }
      timer = setTimeout(settle, 10_000);
    });
  },
});
container
  .bind<AutoresearchStorageClient>(AUTORESEARCH_STORAGE_CLIENT)
  .toConstantValue({
    save: async (run) => {
      await trpcClient.autoresearch.save.mutate(run);
    },
    listOpen: () => trpcClient.autoresearch.listOpen.query(),
    listByTask: (taskId) =>
      trpcClient.autoresearch.listByTask.query({ taskId }),
  });
container.bind<FilePathResolver>(FILE_PATH_RESOLVER).toConstantValue({
  resolve: (file) => window.electronUtils?.getPathForFile?.(file),
});
container.bind(NAVIGATION_TASK_BINDER).toConstantValue(navigationTaskBinder);
initTours();
setPosthogApiClientLogger(logger.scope("posthog-client"));
setPosthogApiClientAppVersion(
  typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "unknown",
);

container.bind<RootLogger>(ROOT_LOGGER).toConstantValue(logger);

const notificationsLog = logger.scope("notifications-adapter");
container.bind<INotifications>(NOTIFICATIONS_SERVICE).toConstantValue({
  notify: (options) => {
    hostTrpcClient.notification.send.mutate(options).catch((err) => {
      notificationsLog.error("Failed to send notification", err);
    });
  },
  showUnreadIndicator: () => {
    hostTrpcClient.notification.showDockBadge.mutate().catch((err) => {
      notificationsLog.error("Failed to show unread indicator", err);
    });
  },
  requestAttention: () => {
    hostTrpcClient.notification.bounceDock.mutate().catch((err) => {
      notificationsLog.error("Failed to request attention", err);
    });
  },
});

container
  .bind<INotificationSettings>(NOTIFICATION_SETTINGS_PROVIDER)
  .toConstantValue({
    get: () => {
      const s = useSettingsStore.getState();
      return {
        desktopNotifications: s.desktopNotifications,
        dockBadgeNotifications: s.dockBadgeNotifications,
        dockBounceNotifications: s.dockBounceNotifications,
        completionSound: s.completionSound,
        completionVolume: s.completionVolume,
        scaleSoundWithTaskLength: s.scaleSoundWithTaskLength,
        customSounds: s.customSounds,
      };
    },
  });

container.bind<IActiveView>(ACTIVE_VIEW_PROVIDER).toConstantValue({
  hasFocus: () => document.hasFocus(),
  // Read the active leaf route directly: AppView collapses the channel routes
  // and drops channelId/dashboardId, which we need to identify a canvas target.
  getActiveTarget: (): NotificationTarget | undefined => {
    const matches = getCurrentMatches();
    const last = matches[matches.length - 1];
    if (!last) return undefined;
    const params = last.params as Record<string, string | undefined>;
    switch (last.routeId) {
      case "/code/tasks/$taskId":
      case "/website/$channelId/tasks/$taskId":
        return params.taskId
          ? { kind: "task", taskId: params.taskId }
          : undefined;
      case "/website/$channelId/dashboards/$dashboardId":
        return params.channelId && params.dashboardId
          ? {
              kind: "canvas",
              channelId: params.channelId,
              dashboardId: params.dashboardId,
            }
          : undefined;
      default:
        return undefined;
    }
  },
});

container.bind<FileWatcherClient>(FILE_WATCHER_CLIENT).toConstantValue({
  start: (repoPath: string) =>
    trpcClient.fileWatcher.start.mutate({ repoPath }),
  stop: (repoPath: string) => trpcClient.fileWatcher.stop.mutate({ repoPath }),
});

// Spoken notifications: synthesize in the host (ElevenLabs, key stays there),
// play in the renderer from a blob URL (host-neutral). Fall back to the system
// voice when no key is set or synthesis fails. speak() resolves when playback
// ends, so the core queue serializes utterances.
const speechLog = logger.scope("speech-adapter");
container.bind<ISpeech>(SPEECH_SERVICE).toConstantValue({
  isSupported: () => isSpeechSupported(),
  speak: async (text, opts) => {
    try {
      const result = await hostTrpcClient.speech.synthesize.query({
        text,
        voiceId: opts?.voiceId || undefined,
      });
      if (result?.audioBase64) {
        await playAudioBase64(result.audioBase64, result.mimeType);
        return;
      }
    } catch (err) {
      speechLog.warn("Synthesis failed; using system voice", err);
    }
    await speakSystemVoice(text);
  },
  stop: () => stopSpeech(),
});

container
  .bind<SpeechSettingsProvider>(SPEECH_SETTINGS_PROVIDER)
  .toConstantValue({
    get: () => {
      const s = useSettingsStore.getState();
      return {
        enabled: s.spokenNotifications,
        voiceId: s.elevenLabsVoiceId || undefined,
      };
    },
  });

container.bind<UserNameProvider>(SPEECH_USER_NAME_PROVIDER).toConstantValue({
  getFirstName: () => {
    try {
      const qc = container.get<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT);
      for (const [, data] of qc.getQueriesData({
        queryKey: authKeys.currentUsers(),
      })) {
        const first = (
          data as { first_name?: string | null } | undefined
        )?.first_name?.trim();
        if (first) return first;
      }
    } catch {
      // best-effort — no name means we just skip the "Hey <name>" prefix
    }
    return undefined;
  },
});

container.bind<ISpeechKeyStore>(SPEECH_KEY_STORE).toConstantValue({
  save: (apiKey) =>
    hostTrpcClient.secureStore.setItem
      .query({ key: ELEVENLABS_API_KEY_STORE_KEY, value: apiKey })
      .then(() => {}),
  clear: () =>
    hostTrpcClient.secureStore.removeItem
      .query({ key: ELEVENLABS_API_KEY_STORE_KEY })
      .then(() => {}),
});

container.bind<ISpeechNotifySettings>(SPEECH_NOTIFY_SETTINGS).toConstantValue({
  get: () => {
    const s = useSettingsStore.getState();
    return {
      enabled: s.spokenNotifications,
      needsInput: s.spokenNotifyNeedsInput,
      completion: s.spokenNotifyCompletion,
      progress: s.spokenNotifyProgress,
      focusMode: s.spokenFocusMode,
    };
  },
});

container
  .bind<FeatureFlags>(FEATURE_FLAGS)
  .toConstantValue(posthogFeatureFlags);

container
  .bind<IAuthSideEffects>(AUTH_SIDE_EFFECTS)
  .to(RendererAuthSideEffects)
  .inSingletonScope();

container.bind(SETUP_STORE).toConstantValue(setupStore);

container
  .bind(HOST_CAPABILITIES)
  .toConstantValue({ localWorkspaces: true } satisfies HostCapabilities);
