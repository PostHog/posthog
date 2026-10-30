import type { CloudRegion } from "@posthog/shared";
import { Box, Text, useInput } from "ink";
import { type ReactElement, useEffect, useRef, useState } from "react";
import { TuiAuth } from "../auth";

const REGIONS: { id: CloudRegion; label: string }[] = [
  { id: "us", label: "US cloud" },
  { id: "eu", label: "EU cloud" },
];

type Step =
  | { kind: "pick" }
  | { kind: "waiting"; url: string | null }
  | { kind: "error"; message: string };

export function SignIn({
  onSignedIn,
}: {
  onSignedIn: (auth: TuiAuth) => void;
}): ReactElement {
  const [selected, setSelected] = useState(0);
  const [step, setStep] = useState<Step>({ kind: "pick" });
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const signIn = (region: CloudRegion): void => {
    abort.current = new AbortController();
    setStep({ kind: "waiting", url: null });
    TuiAuth.login(region, {
      signal: abort.current.signal,
      onAuth: ({ url }) => setStep({ kind: "waiting", url }),
    }).then(onSignedIn, (error: unknown) => {
      if (!abort.current?.signal.aborted) {
        setStep({ kind: "error", message: String(error) });
      }
    });
  };

  useInput((_, key) => {
    if (step.kind === "waiting") {
      if (key.escape) {
        abort.current?.abort();
        setStep({ kind: "pick" });
      }
      return;
    }
    if (key.upArrow) setSelected((index) => Math.max(index - 1, 0));
    if (key.downArrow) {
      setSelected((index) => Math.min(index + 1, REGIONS.length - 1));
    }
    if (key.return) signIn(REGIONS[selected].id);
  });

  return (
    <Box flexDirection="column" padding={1} gap={1}>
      <Text bold>Sign in to PostHog</Text>
      {step.kind === "waiting" ? (
        <Box flexDirection="column">
          <Text>Finish signing in with your browser.</Text>
          {step.url && (
            <Text dimColor>If it didn't open, go to {step.url}</Text>
          )}
          <Text dimColor>Esc to go back</Text>
        </Box>
      ) : (
        <Box flexDirection="column">
          {REGIONS.map((region, index) => (
            <Text key={region.id} inverse={index === selected}>
              {` ${region.label} `}
            </Text>
          ))}
          {step.kind === "error" && (
            <Text color="red">Sign-in failed: {step.message}</Text>
          )}
          <Text dimColor>↑↓ to choose, Enter to sign in</Text>
        </Box>
      )}
    </Box>
  );
}
