/**
 * Names the tools a custom sandbox image carries. The image spec builder
 * writes it into the image's env; the agent reads it at session start, since
 * nothing else tells it what was installed.
 */
export const IMAGE_TOOLS_ENV_KEY = "POSTHOG_IMAGE_TOOLS";
