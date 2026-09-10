import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./logger", () => ({
  networkLog: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

import { networkLog } from "./logger";
import {
  formatBytes,
  formatNetworkLine,
  isLoopbackHost,
  levelForEntry,
  type NetworkLogEntry,
  parseContentLength,
  recordNetworkRequest,
  redactUrl,
  shouldLogUrl,
} from "./network-log";

const mockedNetworkLog = vi.mocked(networkLog);

function entry(overrides: Partial<NetworkLogEntry> = {}): NetworkLogEntry {
  return {
    origin: "main",
    method: "GET",
    url: "https://us.posthog.com/api/projects/",
    status: 200,
    durationMs: 214,
    bytes: 1834,
    ...overrides,
  };
}

describe("isLoopbackHost", () => {
  it.each([
    ["localhost", true],
    ["LOCALHOST", true],
    ["127.0.0.1", true],
    ["127.1.2.3", true],
    ["::1", true],
    ["[::1]", true],
    ["0.0.0.0", true],
    ["us.posthog.com", false],
    ["127posthog.com", false],
    ["mylocalhost.dev", false],
  ])("%s -> %s", (hostname, expected) => {
    expect(isLoopbackHost(hostname)).toBe(expected);
  });
});

describe("shouldLogUrl", () => {
  it.each([
    ["https://us.posthog.com/api/", true],
    ["http://127.0.0.1:54321/trpc", false],
    ["http://localhost:5173/src/main.tsx", false],
    ["http://[::1]:8080/", false],
    ["not a url", true],
  ])("%s -> %s", (url, expected) => {
    expect(shouldLogUrl(url)).toBe(expected);
  });
});

describe("redactUrl", () => {
  it("preserves a plain scheme + host + path url", () => {
    expect(redactUrl("https://us.posthog.com/api/projects/")).toBe(
      "https://us.posthog.com/api/projects/",
    );
  });

  it("replaces the entire query string with a marker", () => {
    // A secret under an arbitrary, non-allowlisted key must not survive.
    const redacted = redactUrl(
      "https://api.example.com/data?my_custom_key=supersecret123&limit=50",
    );
    expect(redacted).toBe("https://api.example.com/data?<redacted>");
    expect(redacted).not.toContain("supersecret123");
    expect(redacted).not.toContain("limit=50");
  });

  it("redacts the query even for otherwise harmless-looking params", () => {
    expect(redactUrl("https://example.com/api?limit=50&offset=10")).toBe(
      "https://example.com/api?<redacted>",
    );
  });

  it("strips userinfo (user:pass@host) credentials", () => {
    const redacted = redactUrl("https://alice:s3cr3tp%40ss@example.com/api");
    expect(redacted).toBe("https://example.com/api");
    expect(redacted).not.toContain("alice");
    expect(redacted).not.toContain("s3cr3t");
  });

  it.each([
    // Key-shaped path segment (e.g. an MCP endpoint keyed in the path).
    [
      "https://mcp.example.com/v1/sk-abc123def456ghi789jkl/messages",
      "https://mcp.example.com/v1/<redacted>/messages",
    ],
    // Long hex digest embedded in the path.
    [
      "https://mcp.example.com/mcp/deadbeefdeadbeefdeadbeefdeadbeef/sse",
      "https://mcp.example.com/mcp/<redacted>/sse",
    ],
    // Long high-entropy token mixing letters and digits.
    [
      "https://api.example.com/hooks/AKIAIOSFODNN7EXAMPLE/run",
      "https://api.example.com/hooks/<redacted>/run",
    ],
  ])("redacts token-like path segments: %s", (url, expected) => {
    const redacted = redactUrl(url);
    expect(redacted).toBe(expected);
  });

  it("keeps short and uuid path segments for debuggability", () => {
    expect(
      redactUrl(
        "https://us.posthog.com/api/projects/12345/insights/550e8400-e29b-41d4-a716-446655440000/",
      ),
    ).toBe(
      "https://us.posthog.com/api/projects/12345/insights/550e8400-e29b-41d4-a716-446655440000/",
    );
  });

  it("redacts a url fragment", () => {
    expect(redactUrl("https://example.com/cb#access_token=abc123")).toBe(
      "https://example.com/cb#<redacted>",
    );
  });

  it("redacts query and token-like segments when the url does not parse", () => {
    expect(redactUrl("/relative/path?token=abc")).toBe(
      "/relative/path?<redacted>",
    );
    expect(redactUrl("/relative/path")).toBe("/relative/path");
    expect(redactUrl("/relative/sk-abc123def456ghi789jkl/x")).toBe(
      "/relative/<redacted>/x",
    );
  });
});

describe("parseContentLength", () => {
  it.each([
    ["1834", 1834],
    ["0", 0],
    ["abc", null],
    ["", null],
    [null, null],
    [undefined, null],
  ])("%s -> %s", (value, expected) => {
    expect(parseContentLength(value)).toBe(expected);
  });
});

describe("formatBytes", () => {
  it.each([
    [1834, "1834B"],
    [0, "0B"],
    [null, "-"],
  ])("%s -> %s", (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected);
  });
});

describe("levelForEntry", () => {
  it.each([
    [200, "info"],
    [204, "info"],
    [301, "info"],
    [399, "info"],
    [400, "warn"],
    [404, "warn"],
    [499, "warn"],
    [500, "error"],
    [503, "error"],
    [null, "error"],
  ])("status %s -> %s", (status, expected) => {
    expect(levelForEntry(entry({ status }))).toBe(expected);
  });
});

describe("formatNetworkLine", () => {
  it("formats a successful request", () => {
    expect(formatNetworkLine(entry())).toBe(
      "[main] GET https://us.posthog.com/api/projects/ -> 200 214ms 1834B",
    );
  });

  it("formats a failed request with the error and no bytes", () => {
    expect(
      formatNetworkLine(
        entry({
          origin: "renderer",
          method: "post",
          status: null,
          error: "TypeError: fetch failed",
          durationMs: 30011.4,
          bytes: null,
        }),
      ),
    ).toBe(
      '[renderer] POST https://us.posthog.com/api/projects/ -> ERR "TypeError: fetch failed" 30011ms -',
    );
  });

  it("redacts secrets in the url before writing the line", () => {
    const line = formatNetworkLine(
      entry({ url: "https://s3.aws.com/log?X-Amz-Signature=abc123" }),
    );
    expect(line).toContain("https://s3.aws.com/log?<redacted>");
    expect(line).not.toContain("abc123");
  });
});

describe("recordNetworkRequest", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("writes at the level matching the outcome", () => {
    recordNetworkRequest(entry({ status: 200 }));
    recordNetworkRequest(entry({ status: 404 }));
    recordNetworkRequest(entry({ status: null, error: "boom" }));

    expect(mockedNetworkLog.info).toHaveBeenCalledOnce();
    expect(mockedNetworkLog.warn).toHaveBeenCalledOnce();
    expect(mockedNetworkLog.error).toHaveBeenCalledOnce();
  });

  it("skips loopback urls", () => {
    recordNetworkRequest(entry({ url: "http://127.0.0.1:54321/trpc" }));
    recordNetworkRequest(entry({ url: "http://localhost:5173/main.tsx" }));

    expect(mockedNetworkLog.info).not.toHaveBeenCalled();
  });

  it("never throws even when the logger does", () => {
    mockedNetworkLog.info.mockImplementationOnce(() => {
      throw new Error("disk full");
    });

    expect(() => recordNetworkRequest(entry())).not.toThrow();
  });
});
