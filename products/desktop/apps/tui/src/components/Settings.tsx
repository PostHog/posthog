import { Box, Text } from "ink";
import type { ReactElement } from "react";
import type { SettingsState } from "../hooks/useSettings";
import { settingsItems } from "../settings";

const LABELS = {
  plan: "Use your ChatGPT plan for local chats",
  login: "Log in to ChatGPT",
  logout: "Log out of ChatGPT",
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
  };
  const asking = view.draft !== null;

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
        <Box key={item} gap={2}>
          <Text wrap="truncate-end">
            {index === view.index && !asking ? "❯ " : "  "}
            <Text inverse={index === view.index && !asking}>
              {LABELS[item]}
            </Text>
          </Text>
          <Text dimColor>{values[item]}</Text>
        </Box>
      ))}
      <Text> </Text>
      {asking ? (
        <Box flexDirection="column">
          <Text dimColor wrap="wrap">
            {view.prompt}
          </Text>
          <Text wrap="truncate-start">
            ❯ {view.draft}
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
        {asking
          ? "Enter send · Esc cancel the login"
          : "↑↓ move · Enter choose · Esc close"}
      </Text>
    </Box>
  );
}
