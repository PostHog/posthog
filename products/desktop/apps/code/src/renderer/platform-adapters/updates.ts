import {
  deriveUpdateUiStatus,
  type MenuCheckToast,
  resolveMenuCheckFromStatus,
  resolveMenuCheckResult,
  updateStore,
} from "@posthog/core/updates/updateStore";
import { resolveService } from "@posthog/di/container";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import {
  UPDATES_CLIENT,
  type UpdatesClient,
} from "@posthog/ui/features/updates/updatesClient";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import { toast } from "@posthog/ui/primitives/toast";
import { logger } from "@posthog/ui/shell/logger";
import { hostTrpcClient } from "@renderer/trpc/client";

const log = logger.scope("updates-host");

const client = resolveService<UpdatesClient>(UPDATES_CLIENT);
const store = updateStore.getState;

function showToast(menuToast: MenuCheckToast): void {
  if (menuToast.kind === "success") {
    toast.success(menuToast.message);
    return;
  }
  toast.error(
    menuToast.message,
    menuToast.description
      ? {
          description: menuToast.description,
        }
      : undefined,
  );
}

void client
  .isEnabled()
  .then((result) => store().setEnabled(result.enabled))
  .catch((error: unknown) => {
    log.error("Failed to get update enabled status", { error });
  });

void client
  .getStatus()
  .then((status) => {
    const update = deriveUpdateUiStatus(status, store().status);
    if (update) {
      store().applyStatusUpdate(update);
    }
  })
  .catch((error: unknown) => {
    log.error("Failed to get update status", { error });
  });

client.onStatus({
  onData: (status) => {
    const update = deriveUpdateUiStatus(status, store().status);
    if (update) {
      store().applyStatusUpdate(update);
    }

    const outcome = resolveMenuCheckFromStatus(
      status,
      store().menuCheckPending,
    );
    if (outcome) {
      if (outcome.clearPending) {
        store().setMenuCheckPending(false);
      }
      if (outcome.toast) {
        showToast(outcome.toast);
      }
    }
  },
  onError: (error) => {
    log.error("Update status subscription error", { error });
    store().setMenuCheckPending(false);
  },
});

client.onReady({
  onData: (data) => {
    store().setReady(data.version);
  },
  onError: (error) => {
    log.error("Update ready subscription error", { error });
  },
});

client.onCheckFromMenu({
  onData: () => {
    store().setMenuCheckPending(true);
    void client
      .check()
      .then((result) => {
        const outcome = resolveMenuCheckResult(result);
        if (outcome) {
          if (outcome.clearPending) {
            store().setMenuCheckPending(false);
          }
          if (outcome.toast) {
            showToast(outcome.toast);
          }
        }
      })
      .catch((error: unknown) => {
        store().setMenuCheckPending(false);
        log.error("Failed to check for updates", { error });
        toast.error("Failed to check for updates");
      });
  },
  onError: (error) => {
    log.error("Update menu check subscription error", { error });
  },
});

// Bridge the "download updates automatically" preference to the core updater.
let lastSyncedAutoDownload: boolean | null = null;
function syncAutoDownload(enabled: boolean): void {
  if (enabled === lastSyncedAutoDownload) return;
  lastSyncedAutoDownload = enabled;
  void hostTrpcClient.updates.setAutoDownload
    .mutate({ enabled })
    .catch((error: unknown) =>
      log.error("Failed to sync auto-download preference", { error }),
    );
}

// Auto-show "What's New" once on the first launch after the version changes.
function maybeShowWhatsNew(): void {
  void hostTrpcClient.os.getAppVersion
    .query()
    .then((currentVersion) => {
      const settings = useSettingsStore.getState();
      const lastSeen = settings.lastSeenChangelogVersion;
      if (lastSeen && lastSeen !== currentVersion) {
        useWhatsNewStore.getState().open();
      }
      if (lastSeen !== currentVersion) {
        settings.setLastSeenChangelogVersion(currentVersion);
      }
    })
    .catch((error: unknown) =>
      log.error("Failed to evaluate What's New", { error }),
    );
}

function onSettingsReady(): void {
  syncAutoDownload(useSettingsStore.getState().downloadUpdatesAutomatically);
  useSettingsStore.subscribe((state) =>
    syncAutoDownload(state.downloadUpdatesAutomatically),
  );
  maybeShowWhatsNew();
}

if (useSettingsStore.persist.hasHydrated()) {
  onSettingsReady();
} else {
  useSettingsStore.persist.onFinishHydration(onSettingsReady);
}
