const TAB_CDP_DOMAINS = new Set([
  "Accessibility",
  "Animation",
  "Audits",
  "CSS",
  "CacheStorage",
  "Console",
  "DOM",
  "DOMDebugger",
  "DOMSnapshot",
  "DOMStorage",
  "Debugger",
  "Emulation",
  "Fetch",
  "HeapProfiler",
  "IndexedDB",
  "Input",
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
  "Security",
]);
const TAB_CDP_DENIED_METHODS = new Set(["Network.getAllCookies"]);

export function isTabScopedCdpMethod(method: string): boolean {
  const domain = method.split(".")[0] ?? "";
  return TAB_CDP_DOMAINS.has(domain) && !TAB_CDP_DENIED_METHODS.has(method);
}
