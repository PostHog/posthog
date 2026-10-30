import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { CloudRegion } from "@posthog/shared";
import { Box, useWindowSize } from "ink";
import { type ReactElement, useMemo, useState } from "react";
import { TuiAuth } from "../auth";
import { createCloud } from "../cloud";
import type { MouseEvents } from "../mouse";
import { WorkList } from "../work";
import { App, type Session } from "./App";

export function Root({
  initialAuth,
  mouse,
}: {
  initialAuth: TuiAuth | null;
  mouse?: MouseEvents;
}): ReactElement {
  const { rows } = useWindowSize();
  const [auth, setAuth] = useState(initialAuth);
  const session = useMemo((): Session | null => {
    if (!auth) return null;
    const api = new PostHogAPIClient(
      auth.apiHost,
      () => auth.getAccessToken(),
      () => auth.refreshAccessToken(),
    );
    return { work: new WorkList(api), ...createCloud(auth, api) };
  }, [auth]);

  const login = async (
    region: CloudRegion,
    onAuth: (url: string) => void,
  ): Promise<void> => {
    setAuth(await TuiAuth.login(region, { onAuth: ({ url }) => onAuth(url) }));
  };
  const logout = (): void => {
    TuiAuth.logout();
    setAuth(null);
  };

  // A full-height frame makes Ink repaint from the top-left of the screen.
  return (
    <Box height={rows} flexDirection="column">
      <App session={session} login={login} logout={logout} mouse={mouse} />
    </Box>
  );
}
