export const QUICK_ASK_TRPC_ROUTES: ReadonlySet<string> = new Set([
  "auth.getState",
  "auth.onStateChanged",
  "auth.getValidAccessToken",
  "auth.refreshAccessToken",
  "os.openExternal",
  "customCloud.get",
  "deepLink.openInboxReport",
]);
