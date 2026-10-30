import { Box, Text } from "ink";
import type { ReactElement } from "react";
import type { SettingsState } from "../hooks/useSettings";
import { settingsItems } from "../settings";

const LABELS = {
  plan: "Use your ChatGPT plan for local chats",
  login: "Log in to ChatGPT",
  logout: "Log out of ChatGPT",
  cloud: "Use your Claude plan for cloud chats",
  token: "Claude token",
  removeToken: "Remove token",
} as const;

export function Settings({
  settings: { view },
}: {
  settings: SettingsState;
}): ReactElement {
  const items = settingsItems(view);
  const values = {
    plan: view.planOn ? "On" : "Off",
    login: view.busy ? "Finish logging in in your browser…" : "",
    logout: view.account ? `Logged in as ${view.account}` : "",
    cloud: view.cloudOn ? "On" : "Off",
    token: view.hasToken ? "Saved" : "Not set",
    removeToken: "",
  };
  const asking = view.draft !== null;
  const pastingToken = asking && view.prompt === null;

  return (
    <Box flexGrow={1} flexDirection="column" paddingX={1} paddingBottom={1}>
      <Text bold>Settings</Text>
      <Text> </Text>
      <Text bold>ChatGPT plan</Text>
      <Text dimColor wrap="wrap">
        Chats you start on this machine run on GPT models from your ChatGPT
        subscription instead of PostHog credits. Cloud chats stay on PostHog.
      </Text>
      {items.map((item, index) => (
        <Box key={item} gap={2} flexDirection="column">
          {item === "cloud" ? (
            <Box flexDirection="column" marginTop={1}>
              <Text bold>Claude plan</Text>
              <Text dimColor wrap="wrap">
                Chats you start in the cloud run Claude Code on your Claude
                subscription. Run `claude setup-token` in another terminal and
                paste the token here; keep the TUI open while a chat starts.
              </Text>
            </Box>
          ) : null}
          <Box gap={2}>
            <Text wrap="truncate-end">
              {index === view.index && !asking ? "❯ " : "  "}
              <Text inverse={index === view.index && !asking}>
                {LABELS[item]}
              </Text>
            </Text>
            <Text dimColor>{values[item]}</Text>
          </Box>
        </Box>
      ))}
      <Text> </Text>
      {asking ? (
        <Box flexDirection="column">
          <Text dimColor wrap="wrap">
            {view.prompt ?? "Claude token"}
          </Text>
          <Text wrap="truncate-start">
            ❯ {pastingToken ? "•".repeat(view.draft?.length ?? 0) : view.draft}
            <Text inverse> </Text>
          </Text>
        </Box>
      ) : null}
      {view.error ? (
        <Text color="red" wrap="wrap">
          {view.error}
        </Text>
      ) : null}
      <Box flexGrow={1} />
      <Text dimColor>
        {pastingToken
          ? "Enter save · Esc cancel"
          : asking
            ? "Enter send · Esc cancel the login"
            : "↑↓ move · Enter choose · paste a Claude token · Esc close"}
      </Text>
    </Box>
  );
}
