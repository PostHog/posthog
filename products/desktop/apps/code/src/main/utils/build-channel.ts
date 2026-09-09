const TEST_CHANNEL = "test";

function buildChannel(): string | undefined {
  return (
    import.meta as unknown as { env?: Record<string, string | undefined> }
  ).env?.VITE_POSTHOG_BUILD_CHANNEL;
}

export function isTestChannelBuild(): boolean {
  return buildChannel() === TEST_CHANNEL;
}

// A release build has no way to edit a custom target, so it must not read or
// write one either.
export function isCustomCloudBuild(): boolean {
  return process.env.POSTHOG_CODE_IS_DEV === "true" || isTestChannelBuild();
}
