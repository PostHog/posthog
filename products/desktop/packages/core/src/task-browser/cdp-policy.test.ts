import { describe, expect, it } from "vitest";
import { isAllowedCdpCall } from "./cdp-policy";

describe("isAllowedCdpCall", () => {
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
    ["Fetch.enable", false],
    ["Security.setIgnoreCertificateErrors", false],
    ["Page.addScriptToEvaluateOnNewDocument", false],
    ["Page.setBypassCSP", false],
    ["Network.setExtraHTTPHeaders", false],
    ["Network.loadNetworkResource", false],
    ["DOM.setFileInputFiles", false],
    ["Network.getResponseBody", false],
    ["Network.getRequestPostData", false],
    ["Page.createIsolatedWorld", false],
    ["Page.addScriptToEvaluateOnLoad", false],
    ["Page.getResourceContent", false],
    ["not-a-method", false],
  ])("allows %s only when it stays in the tab", (method, allowed) => {
    expect(isAllowedCdpCall(method, {})).toBe(allowed);
  });

  it.each([
    [undefined, true],
    [{}, true],
    [{ ignoreCache: true }, true],
    [{ scriptToEvaluateOnLoad: "" }, true],
    [{ scriptToEvaluateOnLoad: "steal()" }, false],
  ])(
    "allows Page.reload with %o only without a load script",
    (params, allowed) => {
      expect(isAllowedCdpCall("Page.reload", params)).toBe(allowed);
    },
  );
});
