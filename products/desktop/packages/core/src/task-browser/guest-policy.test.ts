import { describe, expect, it } from "vitest";
import {
  createNewWindowLimiter,
  isBlockedPreviewRequest,
  protectedLoopbackPorts,
} from "./guest-policy";

describe("guest policy", () => {
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
    ["the debugging port through a trailing dot", "http://localhost.:9222/"],
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
      "localhost with a trailing dot",
      "https://a.example/",
      "http://localhost./",
      true,
    ],
    [
      "an IPv6 link-local address",
      "https://a.example/",
      "http://[feb0::1]/",
      true,
    ],
    [
      "the benchmarking range",
      "https://a.example/",
      "http://198.18.0.1/",
      true,
    ],
    ["a bare intranet name", "https://a.example/", "http://nas/", true],
    ["a .local name", "https://a.example/", "http://printer.local/", true],
    [
      "a Tailscale name",
      "https://a.example/",
      "https://box.tail1.ts.net/",
      true,
    ],
    [
      "a private address from a page it cannot read",
      "not a url",
      "http://10.0.0.5/",
      true,
    ],
    ["a data URL", "https://a.example/", "data:image/png;base64,AA", false],
    ["a blob URL", "https://a.example/", "blob:https://a.example/1", false],
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
});
