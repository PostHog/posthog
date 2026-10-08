export function isCloudRun(
  meta: { environment?: "local" | "cloud" } | undefined,
): boolean {
  if (meta?.environment) {
    return meta.environment === "cloud";
  }
  return !!process.env.IS_SANDBOX;
}
