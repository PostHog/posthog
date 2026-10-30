import { type ReactElement, useState } from "react";
import type { TuiAuth } from "../auth";
import { App } from "./App";
import { SignIn } from "./SignIn";

export function Root({
  initialAuth,
}: {
  initialAuth: TuiAuth | null;
}): ReactElement {
  const [auth, setAuth] = useState(initialAuth);
  return auth ? <App /> : <SignIn onSignedIn={setAuth} />;
}
