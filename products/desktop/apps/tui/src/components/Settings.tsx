import { Box, Text } from "ink";
import type { ReactElement } from "react";
import { billingNotice } from "../billing";
import type { SettingsState } from "../hooks/useSettings";
import { settingsItems } from "../settings";

const LABELS = {
  login: "Log in to ChatGPT",
  logout: "Log out of ChatGPT",
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
    login: view.busy ? "Finish logging in in your browser…" : "",
    logout: view.account ? `Logged in as ${view.account}` : "",
    token: view.hasToken ? "Saved" : "Not set",
    removeToken: "",
  };
  const asking = view.draft !== null;
  const pastingToken = asking && view.prompt === null;

  return (
    <Box flexGrow={1} flexDirection="column" paddingX={1} paddingBottom={1}>
      <Text bold>Settings</Text>
      <Text> </Text>
      <Text>
        {billingNotice(view.billing)}
        <Text dimColor> · change with /billing</Text>
      </Text>
      <Text dimColor wrap="wrap">
        On your ChatGPT plan, chats here run pi on GPT and cloud chats run Codex
        on the account connected in Desktop. On your Claude plan, cloud chats
        run Claude Code with the token below; keep the TUI open while one
        starts.
      </Text>
      <Text> </Text>
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
      <Text dimColor wrap="wrap">
        Run `claude setup-token` in another terminal, then paste the token here.
      </Text>
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
