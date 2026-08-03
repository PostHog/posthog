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
  it.each([
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "code",
    "signature",
    "api_key",
    "apikey",
    "client_secret",
    "password",
    "session",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
  ])("redacts %s query param", (param) => {
    const redacted = redactUrl(`https://example.com/path?${param}=hunter2`);
    expect(redacted).not.toContain("hunter2");
    expect(redacted).toContain(`${param}=***`);
  });

  it("redacts case-insensitively", () => {
    expect(redactUrl("https://s3.aws.com/log?X-Amz-Signature=abc123")).toBe(
      "https://s3.aws.com/log?X-Amz-Signature=***",
    );
  });

  it("collapses repeated sensitive params into one redacted value", () => {
    const redacted = redactUrl("https://example.com/?token=a&token=b");
    expect(redacted).not.toContain("=a");
    expect(redacted).not.toContain("=b");
    expect(redacted).toContain("token=***");
  });

  it("leaves non-sensitive params untouched", () => {
    expect(redactUrl("https://example.com/api?limit=50&offset=10")).toBe(
      "https://example.com/api?limit=50&offset=10",
    );
  });

  it("strips the whole query when the url does not parse", () => {
    expect(redactUrl("/relative/path?token=abc")).toBe(
      "/relative/path?<redacted>",
    );
    expect(redactUrl("/relative/path")).toBe("/relative/path");
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

  it("redacts sensitive query params in the line", () => {
    const line = formatNetworkLine(
      entry({ url: "https://s3.aws.com/log?X-Amz-Signature=abc123" }),
    );
    expect(line).toContain("X-Amz-Signature=***");
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
