import { describe, expect, it } from "vitest";
import { isTabScopedCdpMethod } from "./cdp-policy";

describe("isTabScopedCdpMethod", () => {
  it.each([
    ["Runtime.evaluate", true],
    ["Page.navigate", true],
    ["Input.dispatchMouseEvent", false],
    ["Input.dispatchKeyEvent", false],
    ["Target.getTargets", false],
    ["Target.attachToTarget", false],
    ["Target.sendMessageToTarget", false],
    ["Browser.getVersion", false],
    ["Storage.getCookies", false],
    ["Network.getAllCookies", false],
    ["Network.getCookies", false],
    ["Network.setCookie", false],
    ["IndexedDB.requestData", false],
    ["DOMStorage.getDOMStorageItems", false],
    ["CacheStorage.requestEntries", false],
    ["SystemInfo.getInfo", false],
    ["Tracing.start", false],
    ["not-a-method", false],
  ])("allows %s only when it stays in the tab", (method, allowed) => {
    expect(isTabScopedCdpMethod(method)).toBe(allowed);
  });
});
