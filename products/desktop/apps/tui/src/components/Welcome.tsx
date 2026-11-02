import { Box, Text, useWindowSize } from "ink";
import type { ReactElement } from "react";
import type { OpenModal } from "../hooks/useSheets";
import { renderSheet } from "../sheet";
import { BRAND_STRIPES } from "./Sidebar";

// Where a first run is: picking a PostHog, waiting on the browser, picking who pays, or signing in to the plan picked.
export type WelcomeStep =
  | "signIn"
  | "signingIn"
  | "billing"
  | "token"
  | "chatgpt";

const STEPS: { step: WelcomeStep[]; label: string; plan?: true }[] = [
  { step: ["signIn", "signingIn"], label: "Sign in" },
  { step: ["billing"], label: "Who pays" },
  { step: ["token"], label: "Claude token", plan: true },
  { step: ["chatgpt"], label: "ChatGPT", plan: true },
];

const MAX_WIDTH = 72;

// The first run's screen: the welcome and its current sheet alone, with the app's chrome held back until a session exists.
export function Welcome({
  step,
  modal,
  notice,
}: {
  step: WelcomeStep;
  modal: OpenModal | undefined;
  notice: string | null;
}): ReactElement {
  const { columns } = useWindowSize();
  const width = Math.max(20, Math.min(MAX_WIDTH, columns - 4));
  // A plan's own step only exists on that plan, so it shows once reached.
  const steps = STEPS.filter(
    (entry) => !entry.plan || entry.step.includes(step),
  );
  const sheet = modal ? renderSheet(modal.sheet, modal.index, width) : [];
  return (
    <Box flexGrow={1} alignItems="center" justifyContent="center">
      <Box width={width} flexDirection="column">
        <Text>
          {BRAND_STRIPES.map((color) => (
            <Text key={color} backgroundColor={color}>
              {" "}
            </Text>
          ))}
          <Text bold> Welcome to PostHog</Text>
        </Text>
        <Text dimColor wrap="wrap">
          Chats run on PostHog credits, your Claude plan, or your ChatGPT plan.
        </Text>
        <Text> </Text>
        <Text>
          {steps.map((entry, index) => (
            <Text key={entry.label}>
              {index > 0 ? <Text dimColor> › </Text> : null}
              <Text
                bold={entry.step.includes(step)}
                dimColor={!entry.step.includes(step)}
              >
                {index + 1} {entry.label}
              </Text>
            </Text>
          ))}
        </Text>
        {sheet.map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: drawn lines have no identity of their own
          <Text key={index}>{line || " "}</Text>
        ))}
        {notice ? (
          <Text wrap="wrap">
            {sheet.length === 0 ? "\n" : ""}
            {notice}
          </Text>
        ) : null}
      </Box>
    </Box>
  );
}
