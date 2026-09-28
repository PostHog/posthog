import { describe, expect, it } from "vitest";
import { isTabScopedCdpMethod } from "./cdp-policy";

describe("isTabScopedCdpMethod", () => {
  it.each([
    ["Runtime.evaluate", true],
    ["Page.navigate", true],
    ["Page.addScriptToEvaluateOnNewDocument", true],
    ["Network.getResponseBody", true],
    ["Input.dispatchMouseEvent", true],
    ["Debugger.setBreakpointByUrl", true],
    ["Target.getTargets", false],
    ["Target.attachToTarget", false],
    ["Browser.getVersion", false],
    ["Browser.setDownloadBehavior", false],
    ["Storage.getCookies", false],
    ["Tracing.start", false],
    ["SystemInfo.getInfo", false],
    ["DOM.setFileInputFiles", false],
    ["Network.loadNetworkResource", false],
    ["Page.setDownloadBehavior", false],
    ["Network.getCookies", false],
    ["Network.getAllCookies", false],
    ["Network.setCookie", false],
    ["Network.clearBrowserCookies", false],
    ["CacheStorage.requestCacheNames", false],
    ["not-a-method", false],
  ])("allows %s only when it stays in the tab", (method, allowed) => {
    expect(isTabScopedCdpMethod(method)).toBe(allowed);
  });
});
