import { Box, Text } from "ink";
import type { ReactElement } from "react";
import type { SettingsState } from "../hooks/useSettings";
import { settingsItems } from "../settings";

const LABELS = {
  plan: "Use your Claude plan for local chats",
  token: "Claude token",
  remove: "Remove token",
} as const;

export function Settings({
  settings: { view },
}: {
  settings: SettingsState;
}): ReactElement {
  const items = settingsItems(view);
  const values = {
    plan: view.planOn ? "On" : "Off",
    token: view.hasToken ? "Saved" : "Not set",
    remove: "",
  };
  const pasting = view.draft !== null;

  return (
    <Box flexGrow={1} flexDirection="column" paddingX={1} paddingBottom={1}>
      <Text bold>Settings</Text>
      <Text> </Text>
      <Text bold>Claude plan</Text>
      <Text dimColor wrap="wrap">
        Chats you start on this machine run on your Claude subscription instead
        of PostHog credits. Cloud chats stay on PostHog.
      </Text>
      {items.map((item, index) => (
        <Box key={item} gap={2}>
          <Text wrap="truncate-end">
            {index === view.index && !pasting ? "❯ " : "  "}
            <Text inverse={index === view.index && !pasting}>
              {LABELS[item]}
            </Text>
          </Text>
          <Text dimColor>{values[item]}</Text>
        </Box>
      ))}
      <Text> </Text>
      <Text dimColor wrap="wrap">
        Run `claude setup-token` in another terminal, then paste the token here.
      </Text>
      {pasting ? (
        <Text wrap="truncate-start">
          Token ❯ {"•".repeat(view.draft?.length ?? 0)}
          <Text inverse> </Text>
        </Text>
      ) : null}
      {view.error ? (
        <Text color="red" wrap="wrap">
          {view.error}
        </Text>
      ) : null}
      <Box flexGrow={1} />
      <Text dimColor>
        {pasting
          ? "Enter save · Esc cancel"
          : "↑↓ move · Enter choose · paste a token · Esc close"}
      </Text>
    </Box>
  );
}
