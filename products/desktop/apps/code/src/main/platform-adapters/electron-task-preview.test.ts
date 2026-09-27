import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  app: { commandLine: { getSwitchValue: () => "" } },
  session: { fromPartition: vi.fn() },
  webContents: { fromId: vi.fn() },
}));

import {
  authorizeTaskPreview,
  createNewWindowLimiter,
  isBlockedPreviewRequest,
  protectedLoopbackPorts,
} from "./electron-task-preview";

describe("task preview helpers", () => {
  it("lets a page open only a few new windows at a time", () => {
    let now = 0;
    const mayOpen = createNewWindowLimiter(() => now);
    expect([mayOpen(), mayOpen(), mayOpen(), mayOpen()]).toEqual([
      true,
      true,
      true,
      false,
    ]);
    now = 10_000;
    expect(mayOpen()).toBe(true);
  });

  it.each([
    ["the debugging port", "http://localhost:9222/json"],
    ["the app's own dev server", "http://127.0.0.1:5173/"],
    ["the debugging port through 0.0.0.0", "http://0.0.0.0:9222/json"],
    [
      "the debugging port through a mapped address",
      "http://[::ffff:7f00:1]:9222/",
    ],
  ])("blocks a local page from reaching %s", (_name, requestUrl) => {
    const ports = protectedLoopbackPorts("9222", "http://localhost:5173/");
    expect(
      isBlockedPreviewRequest("http://localhost:3000/", requestUrl, ports),
    ).toBe(true);
    expect(
      isBlockedPreviewRequest(
        "http://localhost:3000/",
        "http://localhost:3000/app.js",
        ports,
      ),
    ).toBe(false);
  });

  it.each([
    ["localhost", "https://a.modal.host/", "http://localhost:8000/", true],
    [
      "a loopback address",
      "https://a.modal.host/",
      "http://127.0.0.1:5432/",
      true,
    ],
    ["an IPv6 loopback", "https://a.modal.host/", "http://[::1]:3000/", true],
    [
      "an IPv4-mapped loopback",
      "https://a.modal.host/",
      "http://[::ffff:127.0.0.1]:3000/",
      true,
    ],
    [
      "an IPv4-mapped private address",
      "https://a.modal.host/",
      "http://[::ffff:192.168.1.1]/",
      true,
    ],
    ["a home router", "https://a.modal.host/", "http://192.168.1.1/", true],
    ["a private network", "https://a.modal.host/", "ws://10.0.0.5:9000/", true],
    [
      "cloud metadata",
      "https://a.modal.host/",
      "http://169.254.169.254/",
      true,
    ],
    ["a file", "https://a.modal.host/", "file:///etc/passwd", true],
    [
      "a public site",
      "https://a.modal.host/",
      "https://cdn.example.com/a.js",
      false,
    ],
    [
      "its own sandbox",
      "https://a.modal.host/",
      "wss://a.modal.host/hmr",
      false,
    ],
    [
      "a local preview's own server",
      "http://localhost:5173/",
      "http://localhost:5173/src/main.tsx",
      false,
    ],
  ])(
    "blocks a request from a preview to %s only when unsafe",
    (_name, pageUrl, requestUrl, blocked) => {
      expect(isBlockedPreviewRequest(pageUrl, requestUrl)).toBe(blocked);
    },
  );

  it("moves the sandbox token into an http-only cookie", async () => {
    const cookies = { set: vi.fn(async () => undefined) };

    await expect(
      authorizeTaskPreview(
        "https://abc-123.modal.host/?_modal_connect_token=secret",
        cookies,
      ),
    ).resolves.toBe("https://abc-123.modal.host/");
    expect(cookies.set).toHaveBeenCalledWith({
      url: "https://abc-123.modal.host",
      name: "_modal_connect_token",
      value: "secret",
      path: "/",
      secure: true,
      httpOnly: true,
      sameSite: "strict",
    });

    await expect(
      authorizeTaskPreview(
        "https://evil.example.com/?_modal_connect_token=secret",
        cookies,
      ),
    ).resolves.toBeNull();
    await expect(
      authorizeTaskPreview(
        "http://localhost:3000/?_modal_connect_token=secret",
        cookies,
      ),
    ).resolves.toBeNull();
    expect(cookies.set).toHaveBeenCalledOnce();
  });
});
