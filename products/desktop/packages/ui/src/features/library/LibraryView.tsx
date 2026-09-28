import { ArrowSquareOut, Books, Warning } from "@phosphor-icons/react";
import { getAuthIdentity } from "@posthog/core/auth/authIdentity";
import { useService } from "@posthog/di/react";
import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  EMBEDDED_WEB_APP_SOURCE,
  type IEmbeddedWebAppSource,
} from "@posthog/platform/embedded-web-app";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useLogoutMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useRouterState } from "@tanstack/react-router";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { libraryIsland } from "./libraryIsland";
import { useLibraryIslandStore } from "./libraryIslandStore";
import { toWebAppLocation } from "./libraryPaths";

/** Library runs the PostHog web app in this pane. See `libraryIsland` for how it stays mounted. */
export function LibraryView() {
  useSetHeaderContent(null);

  const source = useService<IEmbeddedWebAppSource>(EMBEDDED_WEB_APP_SOURCE);
  const config = useMemo(() => source.getConfig(), [source]);
  const authState = useAuthStateValue((state) => state);
  const identity = getAuthIdentity(authState);
  const cloudUrl = authState.cloudRegion
    ? getCloudUrlFromRegion(authState.cloudRegion)
    : null;

  const location = useRouterState({ select: (state) => state.location });
  const webAppLocation = toWebAppLocation({
    pathname: location.pathname,
    search: location.searchStr,
    hash: location.hash ? `#${location.hash}` : "",
  });
  const webAppUrl = webAppLocation
    ? `${webAppLocation.pathname}${webAppLocation.search}${webAppLocation.hash}`
    : "/";

  const openInBrowser = (): void => {
    if (cloudUrl) openExternalUrl(`${cloudUrl}${webAppUrl}`);
  };

  if (!config || !identity || !cloudUrl) {
    return <LibraryUnavailable configured={!!config} onOpen={openInBrowser} />;
  }

  return (
    <LibraryIsland
      config={config}
      identity={identity}
      cloudUrl={cloudUrl}
      webAppUrl={webAppUrl}
      onOpenInBrowser={openInBrowser}
    />
  );
}

function LibraryIsland({
  config,
  identity,
  cloudUrl,
  webAppUrl,
  onOpenInBrowser,
}: {
  config: NonNullable<ReturnType<IEmbeddedWebAppSource["getConfig"]>>;
  identity: string;
  cloudUrl: string;
  webAppUrl: string;
  onOpenInBrowser: () => void;
}) {
  const slotRef = useRef<HTMLDivElement>(null);
  const status = useLibraryIslandStore((state) => state.status);
  const hostClient = useHostTRPCClient();
  const logout = useLogoutMutation();
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const [attempt, setAttempt] = useState(0);

  const logoutRef = useRef(logout.mutate);
  logoutRef.current = logout.mutate;
  const themeRef = useRef(isDarkMode);
  themeRef.current = isDarkMode;

  useLayoutEffect(() => {
    const slot = slotRef.current;
    if (!slot) return;
    libraryIsland.attach(slot);
    return () => libraryIsland.detach();
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` re-runs the mount after a failure.
  useEffect(() => {
    void libraryIsland.mount(config, {
      identity,
      backendHost: cloudUrl,
      getValidAccessToken: () =>
        hostClient.auth.getValidAccessToken.query().then((r) => r.accessToken),
      refreshAccessToken: () =>
        hostClient.auth.refreshAccessToken.mutate().then((r) => r.accessToken),
      signOut: () => {
        // The web app calls this from its own logout handler, so unmount it after that returns.
        setTimeout(() => libraryIsland.reset(), 0);
        logoutRef.current();
      },
      theme: themeRef.current ? "dark" : "light",
    });
  }, [config, identity, cloudUrl, hostClient, attempt]);

  useEffect(() => {
    libraryIsland.setTheme(isDarkMode ? "dark" : "light");
  }, [isDarkMode]);

  // The web app pushes its own navigations through the shell router, so this only moves it when
  // the shell changes the URL: back, forward, or a link from Today or Ask.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `webAppUrl` is the trigger.
  useEffect(() => {
    libraryIsland.syncLocation();
  }, [webAppUrl, status.state]);

  return (
    <div className="relative h-full min-h-0 w-full">
      <div ref={slotRef} className="h-full w-full" />
      {status.state !== "mounted" && (
        <div className="absolute inset-0 bg-background">
          {status.state === "failed" ? (
            <LibraryFailed
              reason={status.reason}
              onRetry={() => setAttempt((n) => n + 1)}
              onOpen={onOpenInBrowser}
            />
          ) : (
            <LoadingState label="Loading Library" />
          )}
        </div>
      )}
    </div>
  );
}

function LibraryUnavailable({
  configured,
  onOpen,
}: {
  configured: boolean;
  onOpen: () => void;
}) {
  useEffect(() => {
    if (!configured) {
      track(ANALYTICS_EVENTS.LIBRARY_LOADED, { outcome: "unavailable" });
    }
  }, [configured]);

  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Books size={20} />
        </EmptyMedia>
        <EmptyTitle>Library opens in PostHog</EmptyTitle>
        <EmptyDescription>
          Your insights, dashboards, flags and the rest of PostHog open in the
          browser from this app.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="primary" onClick={onOpen}>
          <ArrowSquareOut size={14} />
          Open in PostHog
        </Button>
      </EmptyContent>
    </Empty>
  );
}

function LibraryFailed({
  reason,
  onRetry,
  onOpen,
}: {
  reason: "load_failed" | "version_mismatch";
  onRetry: () => void;
  onOpen: () => void;
}) {
  const versionMismatch = reason === "version_mismatch";
  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Warning size={20} />
        </EmptyMedia>
        <EmptyTitle>
          {versionMismatch ? "Update to use Library" : "Library didn't load"}
        </EmptyTitle>
        <EmptyDescription>
          {versionMismatch
            ? "This version of the app can't run the current PostHog web app. Update the app, or open PostHog in the browser."
            : "Check your connection and try again. You can also open PostHog in the browser."}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <div className="flex gap-2">
          {!versionMismatch && (
            <Button variant="primary" onClick={onRetry}>
              Try again
            </Button>
          )}
          <Button variant="outline" onClick={onOpen}>
            <ArrowSquareOut size={14} />
            Open in PostHog
          </Button>
        </div>
      </EmptyContent>
    </Empty>
  );
}
