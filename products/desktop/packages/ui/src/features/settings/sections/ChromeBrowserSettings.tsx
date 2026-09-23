import { useHostTRPC } from "@posthog/host-router/react";
import { Button } from "@posthog/quill";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useMutation, useQuery } from "@tanstack/react-query";

export function ChromeBrowserSettings() {
  const hostTRPC = useHostTRPC();
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
  const connected = status.data?.status === "connected";
  const connecting =
    reconnect.isPending || status.data?.status === "connecting";
  const canDisconnect = connecting || status.data?.status === "connected";
  const disconnectLabel = connecting
    ? "Cancel connection"
    : "Disconnect Chrome";

  return (
    <SettingsSection label="Browser access">
      <SettingsCard>
        <SettingsCardRow
          label="Google Chrome"
          description="Let local agents use your open tabs, including signed-in accounts."
        >
          <div className="flex min-w-0 flex-col items-end gap-2">
            {connecting && (
              <output className="text-muted-foreground text-xs">
                Approve the connection in Chrome.
              </output>
            )}
            {canDisconnect ? (
              <div className="flex flex-wrap justify-end gap-2">
                {connected && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => reconnect.mutate()}
                  >
                    Allow sessions
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={disconnect.isPending}
                  onClick={() => disconnect.mutate()}
                >
                  {disconnect.isPending && <Spinner aria-hidden="true" />}
                  {disconnectLabel}
                </Button>
              </div>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={busy || !status.data}
                onClick={() => reconnect.mutate()}
              >
                Connect Chrome
              </Button>
            )}
            {(reconnect.isError ||
              disconnect.isError ||
              status.data?.status === "error") && (
              <span className="text-destructive text-xs" role="alert">
                {disconnect.isError
                  ? "Couldn't disconnect from Chrome. Try again."
                  : "Couldn't connect to Chrome. Check Connection help and try again."}
              </span>
            )}
          </div>
        </SettingsCardRow>
        <details className="px-3.5 py-2 text-muted-foreground text-xs">
          <summary className="cursor-pointer">Connection help</summary>
          <div className="mt-2 flex flex-col items-start gap-2">
            <p>
              First, enable remote debugging in Chrome. Then select Connect
              Chrome and approve the request in Chrome.
            </p>
            <Button
              size="sm"
              variant="outline"
              disabled={setup.isPending}
              onClick={() => setup.mutate()}
            >
              {setup.isPending && <Spinner aria-hidden="true" />}
              Open Chrome remote debugging settings
            </Button>
            <p>
              Connect Chrome to allow open local sessions to use your tabs.
              Select Allow sessions to include new sessions. Disconnect to stop
              access for all sessions.
            </p>
            {setup.isError && (
              <span className="text-destructive" role="alert">
                Couldn&apos;t open Chrome settings. Check that Google Chrome is
                installed.
              </span>
            )}
          </div>
        </details>
      </SettingsCard>
    </SettingsSection>
  );
}
