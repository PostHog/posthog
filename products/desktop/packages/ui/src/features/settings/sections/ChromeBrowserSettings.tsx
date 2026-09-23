import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useMutation, useQuery } from "@tanstack/react-query";

const connectionLabels = {
  idle: "Ready to connect",
  connecting: "Waiting for Chrome",
  connected: "Connected",
  disconnected: "Disconnected",
  error: "Connection failed. Check Chrome, then reconnect.",
};

export function ChromeBrowserSettings() {
  const hostTRPC = useHostTRPC();
  const enabled = useSettingsStore((s) => s.browserIntegrationEnabled);
  const setEnabled = useSettingsStore((s) => s.setBrowserIntegrationEnabled);
  const status = useQuery({
    ...hostTRPC.agent.browserStatus.queryOptions(),
    refetchInterval: 2000,
  });
  const reconnect = useMutation({
    ...hostTRPC.agent.reconnectBrowser.mutationOptions(),
    onSettled: () => {
      void status.refetch();
    },
  });
  const disconnect = useMutation({
    ...hostTRPC.agent.disconnectBrowser.mutationOptions(),
    onSettled: () => {
      void status.refetch();
    },
  });
  const setup = useMutation(
    hostTRPC.os.openChromeRemoteDebugging.mutationOptions(),
  );
  const busy = reconnect.isPending || disconnect.isPending;

  return (
    <SettingsSection
      label="Browser access"
      description="Manage Chrome access for local agent sessions"
    >
      <SettingsCard>
        <SettingsCardRow
          label="Google Chrome"
          description={
            <ul className="list-disc space-y-0.5 pl-4">
              <li>Can access open tabs signed in to your accounts</li>
              <li>Enable only for agents you trust</li>
              <li>
                Open Chrome setup, then enable remote debugging and confirm in
                Chrome
              </li>
              <li>
                New local sessions share one connection until you disconnect or
                quit Desktop
              </li>
            </ul>
          }
        >
          <div className="flex min-w-0 flex-col items-end gap-2">
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={setup.isPending}
                onClick={() => setup.mutate()}
              >
                {setup.isPending && <Spinner aria-hidden="true" />}
                Open Chrome setup
              </Button>
              <Switch
                aria-label="Enable Google Chrome browser access"
                checked={enabled}
                disabled={busy}
                onCheckedChange={(checked) => {
                  if (checked) setEnabled(true);
                  else
                    disconnect.mutate(undefined, {
                      onSuccess: () => setEnabled(false),
                    });
                }}
              />
            </div>
            {enabled && (
              <>
                <output className="text-muted-foreground text-xs">
                  {status.data && connectionLabels[status.data.status]}
                </output>
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => reconnect.mutate()}
                  >
                    {reconnect.isPending && <Spinner aria-hidden="true" />}
                    Reconnect Chrome
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      disconnect.isPending ||
                      status.data?.status === "disconnected"
                    }
                    onClick={() => disconnect.mutate()}
                  >
                    {disconnect.isPending && <Spinner aria-hidden="true" />}
                    Disconnect Chrome
                  </Button>
                </div>
              </>
            )}
            {setup.isError && (
              <span className="text-destructive text-xs" role="alert">
                Couldn&apos;t open Chrome setup. Check that Google Chrome is
                installed.
              </span>
            )}
            {(reconnect.isError || disconnect.isError) && (
              <span className="text-destructive text-xs" role="alert">
                Couldn&apos;t change the Chrome connection. Check Chrome and try
                again.
              </span>
            )}
          </div>
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}
