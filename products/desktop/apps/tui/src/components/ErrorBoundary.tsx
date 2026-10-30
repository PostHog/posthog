import { Box, Text, useApp, useInput } from "ink";
import { Component, type ReactElement, type ReactNode } from "react";
import { LOG_PATH, logError } from "../errors";

// Keeps a render error from unmounting the app, which would end the process and the local agents it runs.
// The screen names the error until a reload brings a fixed copy of the code.
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error): { error: Error } {
    return { error };
  }

  componentDidCatch(error: Error): void {
    logError("render", error);
  }

  render(): ReactNode {
    return this.state.error ? (
      <Crashed error={this.state.error} />
    ) : (
      this.props.children
    );
  }
}

function Crashed({ error }: { error: Error }): ReactElement {
  const { exit } = useApp();
  // The app's own keys died with it, so this screen keeps reload and quit.
  useInput((input, key) => {
    if (key.ctrl && input === "r")
      (
        globalThis as { __posthogTuiReload?: () => void }
      ).__posthogTuiReload?.();
    if (key.ctrl && input === "q") exit();
  });
  return (
    <Box flexDirection="column" padding={1}>
      <Text color="red" bold>
        The TUI hit an error: {error.message}
      </Text>
      <Text> </Text>
      <Text>Press Ctrl+R to reload, or Ctrl+Q to quit.</Text>
      <Text>
        Your chats keep running. If an agent is changing the TUI's code, the TUI
        reloads by itself when that change lands.
      </Text>
      <Text> </Text>
      <Text dimColor>Details are in {LOG_PATH}</Text>
    </Box>
  );
}
