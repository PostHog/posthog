import { Box, useWindowSize } from "ink";
import { type ReactElement, useState } from "react";
import type { TuiAuth } from "../auth";
import { App } from "./App";
import { SignIn } from "./SignIn";

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
      {auth ? <App /> : <SignIn onSignedIn={setAuth} />}
    </Box>
  );
}
