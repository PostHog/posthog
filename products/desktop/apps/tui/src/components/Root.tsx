import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { Box, useWindowSize } from "ink";
import { type ReactElement, useMemo, useState } from "react";
import type { TuiAuth } from "../auth";
import { WorkList } from "../work";
import { App } from "./App";
import { SignIn } from "./SignIn";

function Workbench({ auth }: { auth: TuiAuth }): ReactElement {
  const work = useMemo(
    () =>
      new WorkList(
        new PostHogAPIClient(
          auth.apiHost,
          () => auth.getAccessToken(),
          () => auth.refreshAccessToken(),
        ),
      ),
    [auth],
  );
  return <App work={work} />;
}

export function Root({
  initialAuth,
}: {
  initialAuth: TuiAuth | null;
}): ReactElement {
  const { rows } = useWindowSize();
  const [auth, setAuth] = useState(initialAuth);
  // A full-height frame makes Ink repaint from the top-left of the screen.
  return (
    <Box height={rows} flexDirection="column">
      {auth ? <Workbench auth={auth} /> : <SignIn onSignedIn={setAuth} />}
    </Box>
  );
}
