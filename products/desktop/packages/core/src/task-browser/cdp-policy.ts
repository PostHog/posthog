const TAB_CDP_DOMAINS = new Set([
  "Accessibility",
  "Audits",
  "CSS",
  "Console",
  "DOM",
  "DOMDebugger",
  "DOMSnapshot",
  "Debugger",
  "Emulation",
  "Fetch",
  "IO",
  "Input",
  "Inspector",
  "Log",
  "Network",
  "Overlay",
  "Page",
  "Performance",
  "Profiler",
  "Runtime",
  "WebAudio",
  "WebAuthn",
]);

const OUTSIDE_TAB_METHODS = new Set([
  "DOM.setFileInputFiles",
  "Network.clearBrowserCache",
  "Network.clearBrowserCookies",
  "Network.deleteCookies",
  "Network.getAllCookies",
  "Network.getCookies",
  "Network.loadNetworkResource",
  "Network.setCookie",
  "Network.setCookies",
  "Page.setDownloadBehavior",
]);

export function isTabScopedCdpMethod(method: string): boolean {
  const domain = method.split(".")[0] ?? "";
  return TAB_CDP_DOMAINS.has(domain) && !OUTSIDE_TAB_METHODS.has(method);
}
