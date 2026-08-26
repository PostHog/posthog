import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

/**
 * Opt-in switch to run local Codex sessions on the user's own ChatGPT
 * subscription. Hidden unless a Codex install or login is detected, so users
 * without Codex never see it. Detection is existence-only; the sign-in runs
 * through Codex's own login flow into an app-private CODEX_HOME.
 */
export function CodexSubscriptionSettings() {
  const codexModelAccess = useSettingsStore((s) => s.codexModelAccess);
  const setCodexModelAccess = useSettingsStore((s) => s.setCodexModelAccess);
  const hostTRPC = useHostTRPC();
  const queryClient = useQueryClient();
  const [awaitingLogin, setAwaitingLogin] = useState(false);

  const enabled = codexModelAccess === "own-subscription";
  const statusQuery = hostTRPC.agent.codexSubscriptionStatus.queryOptions();
  const { data: status } = useQuery({
    ...statusQuery,
    // Poll only while a browser sign-in is pending, and stop once it lands.
    refetchInterval: (query) =>
      awaitingLogin && query.state.data?.appLoggedIn !== true ? 2000 : false,
  });
  const loggedIn = status?.appLoggedIn === true;

  const login = useMutation({
    ...hostTRPC.agent.codexSubscriptionLoginStart.mutationOptions(),
    onSuccess: ({ authUrl }) => {
      openExternalUrl(authUrl);
      setAwaitingLogin(true);
    },
  });
  const signOut = useMutation({
    ...hostTRPC.agent.codexSubscriptionSignOut.mutationOptions(),
    onSettled: () => {
      setAwaitingLogin(false);
      void queryClient.invalidateQueries({ queryKey: statusQuery.queryKey });
    },
  });

  const detected =
    status && (status.cliInstalled || status.credentialFilePresent || loggedIn);
  if (!detected && !enabled) {
    return null;
  }

  return (
    <SettingRow
      label="Use your ChatGPT subscription"
      description="Codex sessions run on your ChatGPT plan instead of PostHog credits. Usage counts against your ChatGPT plan limits"
    >
      <div className="flex flex-col items-end gap-2">
        <Switch
          size="sm"
          checked={enabled}
          onCheckedChange={(checked) =>
            setCodexModelAccess(
              checked ? "own-subscription" : "posthog-gateway",
            )
          }
        />
        {enabled && !loggedIn && (
          <div className="flex flex-col items-end gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={login.isPending}
              onClick={() => login.mutate()}
            >
              {login.isPending
                ? "Opening browser..."
                : awaitingLogin
                  ? "Try again"
                  : "Connect ChatGPT account"}
            </Button>
            <span className="text-right text-(--gray-11) text-[12px]">
              {awaitingLogin
                ? "Finish signing in with your browser. This updates automatically"
                : "Sessions keep using PostHog credits until you connect"}
            </span>
          </div>
        )}
        {enabled && loggedIn && (
          <div className="flex items-center gap-2">
            <span className="text-(--gray-11) text-[12px]">
              ChatGPT account connected
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              Sign out
            </Button>
          </div>
        )}
      </div>
    </SettingRow>
  );
}
