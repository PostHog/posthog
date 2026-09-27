import { useServiceOptional } from "@posthog/di/react";
import {
  type ITaskBrowserHost,
  TASK_BROWSER_HOST,
  type TaskBrowserSettings,
} from "@posthog/platform/task-browser";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Badge,
  Button,
  Switch,
} from "@posthog/quill";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { siteName } from "@posthog/ui/features/task-preview/browserAddress";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { toast } from "@posthog/ui/primitives/toast";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const settingsQueryKey = ["task-browser", "settings"] as const;

export function BrowserSettings() {
  const host = useServiceOptional<ITaskBrowserHost>(TASK_BROWSER_HOST);
  if (!host) return null;
  return <BrowserSettingsContent host={host} />;
}

function BrowserSettingsContent({ host }: { host: ITaskBrowserHost }) {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({
    queryKey: settingsQueryKey,
    queryFn: () => host.getSettings(),
    staleTime: 0,
  });
  const [pendingOrigin, setPendingOrigin] = useState<string | null>(null);
  const [savingCdp, setSavingCdp] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);

  const update = (next: Partial<TaskBrowserSettings>) =>
    queryClient.setQueryData<TaskBrowserSettings>(
      settingsQueryKey,
      (current) => (current ? { ...current, ...next } : current),
    );

  const removeSite = async (origin: string) => {
    setPendingOrigin(origin);
    try {
      await host.setSitePolicy(origin, null);
      const sites = { ...settingsQuery.data?.sites };
      delete sites[origin];
      update({ sites });
    } catch {
      toast.error("Couldn't remove the site. Try again.");
    } finally {
      setPendingOrigin(null);
    }
  };

  const setFullCdpAccess = async (enabled: boolean) => {
    setSavingCdp(true);
    try {
      await host.setFullCdpAccess(enabled);
      update({ fullCdpAccess: enabled });
    } catch {
      toast.error("Couldn't save the setting. Try again.");
    } finally {
      setSavingCdp(false);
    }
  };

  const clearBrowsingData = async () => {
    setClearing(true);
    try {
      await host.clearBrowsingData();
      toast.success("Browsing data cleared", { alwaysShow: true });
    } catch {
      toast.error("Couldn't clear browsing data. Try again.");
    } finally {
      setClearing(false);
    }
  };

  if (settingsQuery.isPending) return <LoadingState />;
  if (settingsQuery.isError) {
    return (
      <SettingsCard>
        <SettingsCardRow
          label="Couldn't load browser settings"
          description="Try again. If it keeps happening, restart the app."
        >
          <Button
            variant="outline"
            size="sm"
            onClick={() => void settingsQuery.refetch()}
          >
            Try again
          </Button>
        </SettingsCardRow>
      </SettingsCard>
    );
  }

  const sites = Object.entries(settingsQuery.data.sites).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  return (
    <div className="flex flex-col gap-6">
      <SettingsSection
        label="Sites"
        description="The agent asks before it uses a new site in the in-app browser. Sites you always allow or block show here."
      >
        <SettingsCard>
          {sites.length === 0 ? (
            <SettingsCardRow
              label="No saved sites"
              description="When you choose Always allow or Block for a site, it shows here."
            />
          ) : (
            sites.map(([origin, policy]) => (
              <SettingsCardRow
                key={origin}
                label={
                  <span className="flex items-center gap-2">
                    <span className="truncate" title={origin}>
                      {siteName(origin)}
                    </span>
                    <Badge
                      variant={policy === "allow" ? "success" : "destructive"}
                    >
                      {policy === "allow" ? "Allowed" : "Blocked"}
                    </Badge>
                  </span>
                }
              >
                <Button
                  variant="outline"
                  size="sm"
                  data-attr="browser-settings-remove-site"
                  disabled={pendingOrigin !== null}
                  onClick={() => void removeSite(origin)}
                >
                  {pendingOrigin === origin ? "Removing…" : "Remove"}
                </Button>
              </SettingsCardRow>
            ))
          )}
        </SettingsCard>
      </SettingsSection>
      <SettingsSection label="Developer">
        <SettingsCard>
          <SettingsCardRow
            label="Full DevTools access"
            description="Let the agent use the Chrome DevTools Protocol. It still asks you once for each task, because it can then read and change everything on the page, including network traffic."
          >
            <Switch
              data-attr="browser-settings-full-cdp"
              checked={settingsQuery.data.fullCdpAccess}
              disabled={savingCdp}
              onCheckedChange={(checked) => void setFullCdpAccess(checked)}
            />
          </SettingsCardRow>
          <SettingsCardRow
            label="Clear browsing data"
            description="Remove cookies, storage and cache from the in-app browser. This signs you out of sites you used there."
          >
            <Button
              variant="outline"
              size="sm"
              data-attr="browser-settings-clear-data"
              onClick={() => setConfirmClear(true)}
            >
              Clear data
            </Button>
            <AlertDialog open={confirmClear} onOpenChange={setConfirmClear}>
              <AlertDialogContent className="max-w-md">
                <AlertDialogHeader>
                  <AlertDialogTitle>Clear browsing data?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This removes cookies, storage and cache from the in-app
                    browser, and signs you out of every site you used there.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogClose
                    render={<Button variant="outline">Cancel</Button>}
                  />
                  <Button
                    variant="primary"
                    loading={clearing}
                    data-attr="browser-settings-clear-data-confirm"
                    onClick={() =>
                      void clearBrowsingData().then(() =>
                        setConfirmClear(false),
                      )
                    }
                  >
                    Clear data
                  </Button>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </SettingsCardRow>
        </SettingsCard>
      </SettingsSection>
    </div>
  );
}
