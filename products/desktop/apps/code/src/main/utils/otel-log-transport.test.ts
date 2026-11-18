import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./env", () => ({
  getAppVersion: () => process.env.POSTHOG_CODE_VERSION,
}));

const mockEmit = vi.fn();
const mockForceFlush = vi.fn(() => Promise.resolve());
const mockShutdown = vi.fn(() => Promise.resolve());

vi.mock("@opentelemetry/exporter-logs-otlp-http", () => ({
  OTLPLogExporter: class {
    constructor(public config: unknown) {}
  },
}));

vi.mock("@opentelemetry/sdk-logs", () => ({
  BatchLogRecordProcessor: class {
    constructor(
      public _exporter: unknown,
      public _opts: unknown,
    ) {}
  },
  LoggerProvider: class {
    constructor(public _opts: unknown) {}
    getLogger() {
      return { emit: mockEmit };
    }
    forceFlush() {
      return mockForceFlush();
    }
    shutdown() {
      return mockShutdown();
    }
  },
}));

vi.mock("@opentelemetry/resources", () => ({
  resourceFromAttributes: vi.fn((attrs: Record<string, string>) => attrs),
}));

vi.mock("@opentelemetry/semantic-conventions", () => ({
  ATTR_SERVICE_NAME: "service.name",
}));

describe("otel-log-transport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    vi.unstubAllEnvs();
    process.env.POSTHOG_CODE_VERSION = "1.0.0-test";
  });

  describe("initOtelTransport", () => {
    it("returns a no-op transport when API key is missing", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "https://test.posthog.com");

      const { initOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      const transport = initOtelTransport("info");

      expect(transport.level).toBe(false);
      expect(transport.transforms).toEqual([]);
    });

    it("returns a no-op transport when API host is missing", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test123");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "");

      const { initOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      const transport = initOtelTransport("info");

      expect(transport.level).toBe(false);
      expect(transport.transforms).toEqual([]);
    });

    it("creates a transport when API key is present", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test123");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "https://test.posthog.com");

      const { initOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      const transport = initOtelTransport("info");

      expect(transport.level).toBe("info");
      expect(transport.transforms).toEqual([]);
    });

    it("maps all electron-log severity levels correctly", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test123");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "https://test.posthog.com");

      const { initOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      const transport = initOtelTransport("silly");

      const levels = [
        { level: "error", text: "ERROR" },
        { level: "warn", text: "WARN" },
        { level: "info", text: "INFO" },
        { level: "verbose", text: "DEBUG" },
        { level: "debug", text: "DEBUG" },
        { level: "silly", text: "TRACE" },
      ];

      for (const { level, text } of levels) {
        mockEmit.mockClear();
        transport({
          level,
          data: [`test ${level} message`],
          date: new Date(),
        } as never);

        expect(mockEmit).toHaveBeenCalledWith(
          expect.objectContaining({
            severityText: text,
          }),
        );
      }
    });

    it("includes scope in attributes when present", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test123");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "https://test.posthog.com");

      const { initOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      const transport = initOtelTransport("info");

      transport({
        level: "info",
        data: ["scoped message"],
        date: new Date(),
        scope: "my-service",
      } as never);

      expect(mockEmit).toHaveBeenCalledWith(
        expect.objectContaining({
          attributes: { "log.scope": "my-service" },
        }),
      );
    });

    it("omits scope from attributes when not present", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test123");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "https://test.posthog.com");

      const { initOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      const transport = initOtelTransport("info");

      transport({
        level: "info",
        data: ["no scope"],
        date: new Date(),
      } as never);

      expect(mockEmit).toHaveBeenCalledWith(
        expect.objectContaining({
          attributes: {},
        }),
      );
    });

    it("formats mixed data types in body", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test123");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "https://test.posthog.com");

      const { initOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      const transport = initOtelTransport("info");

      transport({
        level: "info",
        data: ["message", { key: "value" }, 42],
        date: new Date(),
      } as never);

      expect(mockEmit).toHaveBeenCalledWith(
        expect.objectContaining({
          body: 'message {"key":"value"} 42',
        }),
      );
    });

    it("redacts tokens, secret headers and the proxy path token before export", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test123");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "https://test.posthog.com");

      const { initOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      const transport = initOtelTransport("info");

      transport({
        level: "info",
        data: [
          "minted phe_secret1 for pha_secret2",
          {
            headers: { authorization: "Bearer anything" },
            refresh: "phr_secret3",
          },
          new Error(`proxy http://127.0.0.1:5000/${"t".repeat(43)}/v1 failed`),
        ],
        date: new Date(),
      } as never);

      const body = mockEmit.mock.calls[0][0].body as string;
      for (const secret of [
        "secret1",
        "secret2",
        "secret3",
        "Bearer anything",
        "t".repeat(43),
      ]) {
        expect(body).not.toContain(secret);
      }
      expect(body).toContain("[REDACTED]");
    });

    it("masks name/value header records and redacts the String() fallback", async () => {
      const { formatBody } = await import("@main/utils/otel-log-transport");

      expect(
        formatBody([[{ name: "Authorization", value: "Bearer abc123" }]]),
      ).toBe('[{"name":"Authorization","value":"[REDACTED]"}]');
      expect(formatBody([["pha_secret5", 1n]])).toBe("[REDACTED],1");
    });

    it("falls back to String() for a circular value without walking it", async () => {
      const { formatBody } = await import("@main/utils/otel-log-transport");
      let reads = 0;
      const circular: Record<string, unknown> = {
        get token() {
          reads += 1;
          return "pha_secret4";
        },
      };
      circular.self = circular;

      expect(formatBody([circular])).toBe("[object Object]");
      expect(reads).toBe(1);
    });

    it("formats Error objects with message and stack", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test123");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "https://test.posthog.com");

      const { initOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      const transport = initOtelTransport("info");

      const error = new Error("test error");
      transport({
        level: "error",
        data: ["failed:", error],
        date: new Date(),
      } as never);

      const call = mockEmit.mock.calls[0][0];
      expect(call.body).toContain("failed:");
      expect(call.body).toContain("test error");
    });
  });

  describe("shutdownOtelTransport", () => {
    it("flushes and shuts down the provider", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test123");
      vi.stubEnv("VITE_POSTHOG_API_HOST", "https://test.posthog.com");

      const { initOtelTransport, shutdownOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      initOtelTransport("info");

      await shutdownOtelTransport();

      expect(mockForceFlush).toHaveBeenCalled();
      expect(mockShutdown).toHaveBeenCalled();
    });

    it("is a no-op when provider was never created", async () => {
      vi.stubEnv("VITE_POSTHOG_API_KEY", "");

      const { initOtelTransport, shutdownOtelTransport } = await import(
        "@main/utils/otel-log-transport"
      );
      initOtelTransport("info");

      await expect(shutdownOtelTransport()).resolves.toBeUndefined();
      expect(mockForceFlush).not.toHaveBeenCalled();
    });
  });
});
