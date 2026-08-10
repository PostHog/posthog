import { POSTHOG_CODE_INTERNAL_CHILD_ENV } from "@posthog/shared/constants";

// Packaged-only: dev builds must stay launchable from dogfooding trees, where
// an app-spawned agent or terminal runs `pnpm dev` with the marker inherited.
export function shouldRefuseInternalChildBoot(
  isPackaged: boolean,
  env: NodeJS.ProcessEnv,
): boolean {
  return isPackaged && Boolean(env[POSTHOG_CODE_INTERNAL_CHILD_ENV]);
}
