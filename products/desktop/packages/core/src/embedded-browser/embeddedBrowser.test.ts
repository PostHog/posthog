import type { IEmbeddedBrowser } from "@posthog/platform/embedded-browser";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EmbeddedBrowserService } from "./embeddedBrowser";

function fakeBrowser(): IEmbeddedBrowser {
  return {
    create: vi.fn().mockResolvedValue(undefined),
    navigate: vi.fn().mockResolvedValue(undefined),
    goBack: vi.fn(),
    goForward: vi.fn(),
    reload: vi.fn(),
    setBounds: vi.fn(),
    setVisible: vi.fn(),
    openDevTools: vi.fn(),
    destroy: vi.fn().mockResolvedValue(undefined),
    getPageState: vi.fn().mockReturnValue(null),
    events: vi.fn(),
  };
}

const bounds = { x: 0, y: 0, width: 800, height: 600 };

describe("EmbeddedBrowserService", () => {
  let browser: IEmbeddedBrowser;
  let service: EmbeddedBrowserService;

  beforeEach(() => {
    browser = fakeBrowser();
    service = new EmbeddedBrowserService(browser);
  });

  it("normalizes the URL before opening", async () => {
    await service.open({ viewId: "v1", url: "localhost:8000", bounds });
    expect(browser.create).toHaveBeenCalledWith({
      viewId: "v1",
      url: "http://localhost:8000/",
      bounds,
    });
  });

  it.each(["file:///etc/passwd", "javascript:alert(1)", "not a url"])(
    "refuses to open %s",
    async (url) => {
      await expect(service.open({ viewId: "v1", url, bounds })).rejects.toThrow(
        /not a loadable web url/i,
      );
      expect(browser.create).not.toHaveBeenCalled();
    },
  );

  it("normalizes the URL before navigating", async () => {
    await service.navigate("v1", "posthog.com");
    expect(browser.navigate).toHaveBeenCalledWith("v1", "https://posthog.com/");
  });

  it("refuses to navigate to a non-web URL", async () => {
    await expect(service.navigate("v1", "file:///x")).rejects.toThrow(
      /not a loadable web url/i,
    );
    expect(browser.navigate).not.toHaveBeenCalled();
  });

  it("forwards view lifecycle calls untouched", async () => {
    service.goBack("v1");
    service.goForward("v1");
    service.reload("v1");
    service.setBounds("v1", bounds);
    service.setVisible("v1", false);
    service.openDevTools("v1");
    await service.destroy("v1");
    expect(browser.goBack).toHaveBeenCalledWith("v1");
    expect(browser.goForward).toHaveBeenCalledWith("v1");
    expect(browser.reload).toHaveBeenCalledWith("v1");
    expect(browser.setBounds).toHaveBeenCalledWith("v1", bounds);
    expect(browser.setVisible).toHaveBeenCalledWith("v1", false);
    expect(browser.openDevTools).toHaveBeenCalledWith("v1");
    expect(browser.destroy).toHaveBeenCalledWith("v1");
  });
});
