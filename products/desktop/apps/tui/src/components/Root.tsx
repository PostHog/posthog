import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { Box, useWindowSize } from "ink";
import { type ReactElement, useMemo, useState } from "react";
import type { TuiAuth } from "../auth";
import { createCloud } from "../cloud";
import type { MouseEvents } from "../mouse";
import { WorkList } from "../work";
import { App } from "./App";
import { SignIn } from "./SignIn";

function Workbench({
  auth,
  mouse,
}: {
  auth: TuiAuth;
  mouse?: MouseEvents;
}): ReactElement {
  const { work, runs, chats, control } = useMemo(() => {
    const api = new PostHogAPIClient(
      auth.apiHost,
      () => auth.getAccessToken(),
      () => auth.refreshAccessToken(),
    );
    return { work: new WorkList(api), ...createCloud(auth, api) };
  }, [auth]);
  return (
    <App
      work={work}
      runs={runs}
      chats={chats}
      control={control}
      mouse={mouse}
    />
  );
}

export function Root({
  initialAuth,
  mouse,
}: {
  initialAuth: TuiAuth | null;
  mouse?: MouseEvents;
}): ReactElement {
  const { rows } = useWindowSize();
  const [auth, setAuth] = useState(initialAuth);
  // A full-height frame makes Ink repaint from the top-left of the screen.
  return (
    <Box height={rows} flexDirection="column">
      {auth ? (
        <Workbench auth={auth} mouse={mouse} />
      ) : (
        <SignIn onSignedIn={setAuth} />
      )}
    </Box>
  );
}
