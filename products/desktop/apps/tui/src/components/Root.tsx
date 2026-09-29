import type { EventEmitter } from "node:events";
import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { Box, useWindowSize } from "ink";
import { type ReactElement, useMemo, useState } from "react";
import type { TuiAuth } from "../auth";
import { createCloudRuns } from "../cloud";
import type { Click } from "../mouse";
import { WorkList } from "../work";
import { App } from "./App";
import { SignIn } from "./SignIn";

type Clicks = EventEmitter<{ click: [Click] }>;

function Workbench({
  auth,
  clicks,
}: {
  auth: TuiAuth;
  clicks?: Clicks;
}): ReactElement {
  const { work, runs } = useMemo(() => {
    const api = new PostHogAPIClient(
      auth.apiHost,
      () => auth.getAccessToken(),
      () => auth.refreshAccessToken(),
    );
    return { work: new WorkList(api), runs: createCloudRuns(auth, api) };
  }, [auth]);
  return <App work={work} runs={runs} clicks={clicks} />;
}

export function Root({
  initialAuth,
  clicks,
}: {
  initialAuth: TuiAuth | null;
  clicks?: Clicks;
}): ReactElement {
  const { rows } = useWindowSize();
  const [auth, setAuth] = useState(initialAuth);
  // A full-height frame makes Ink repaint from the top-left of the screen.
  return (
    <Box height={rows} flexDirection="column">
      {auth ? (
        <Workbench auth={auth} clicks={clicks} />
      ) : (
        <SignIn onSignedIn={setAuth} />
      )}
    </Box>
  );
}
