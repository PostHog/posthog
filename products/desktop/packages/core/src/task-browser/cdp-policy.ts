const TAB_CDP_DOMAINS = new Set([
  "Accessibility",
  "Audits",
  "CacheStorage",
  "CSS",
  "Console",
  "DOM",
  "DOMDebugger",
  "DOMSnapshot",
  "Database",
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

const LOCAL_FILE_METHODS = new Set([
  "DOM.setFileInputFiles",
  "Network.loadNetworkResource",
  "Page.setDownloadBehavior",
]);

export function isTabScopedCdpMethod(method: string): boolean {
  const domain = method.split(".")[0] ?? "";
  return TAB_CDP_DOMAINS.has(domain) && !LOCAL_FILE_METHODS.has(method);
}
