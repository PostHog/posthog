const TAB_CDP_DOMAINS = new Set([
  "Accessibility",
  "Animation",
  "Audits",
  "CSS",
  "Console",
  "DOM",
  "DOMDebugger",
  "DOMSnapshot",
  "Debugger",
  "Emulation",
  "HeapProfiler",
  "LayerTree",
  "Log",
  "Media",
  "Network",
  "Overlay",
  "Page",
  "Performance",
  "PerformanceTimeline",
  "Profiler",
  "Runtime",
]);
const TAB_CDP_DENIED_METHODS = new Set([
  "DOM.setFileInputFiles",
  "Network.loadNetworkResource",
  "Network.replayXHR",
  "Network.setExtraHTTPHeaders",
  "Network.setRequestInterception",
  "Page.addScriptToEvaluateOnNewDocument",
  "Page.navigateToHistoryEntry",
  "Page.setBypassCSP",
  "Page.setDownloadBehavior",
  "Network.clearBrowserCache",
  "Network.clearBrowserCookies",
  "Network.deleteCookies",
  "Network.getAllCookies",
  "Network.getCookies",
  "Network.setCookie",
  "Network.setCookies",
]);

export function isTabScopedCdpMethod(method: string): boolean {
  const domain = method.split(".")[0] ?? "";
  return TAB_CDP_DOMAINS.has(domain) && !TAB_CDP_DENIED_METHODS.has(method);
}
