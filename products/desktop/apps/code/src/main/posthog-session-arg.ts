export const POSTHOG_SESSION_ID_ARG = "--posthog-session-id=";

export function parseSessionIdArg(argv: string[]): string | null {
  return (
    argv
      .find((arg) => arg.startsWith(POSTHOG_SESSION_ID_ARG))
      ?.slice(POSTHOG_SESSION_ID_ARG.length) ?? null
  );
}
