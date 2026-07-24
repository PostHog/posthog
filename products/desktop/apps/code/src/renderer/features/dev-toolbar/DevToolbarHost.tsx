import { DevToolbar } from "./components/DevToolbar";
import { useDevToolbarIntegration } from "./integration";

export function DevToolbarHost() {
  useDevToolbarIntegration();

  return <DevToolbar />;
}
