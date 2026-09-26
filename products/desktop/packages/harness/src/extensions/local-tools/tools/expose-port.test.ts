import { afterEach, describe, expect, it, vi } from "vitest";
import { enabledLocalTools } from "../index";
import {
  checkListener,
  EXPOSE_PORT_TOOL_NAME,
  exposePortSchema,
  reservedPortProblem,
} from "./expose-port";

describe("expose_port tool", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each([
    {
      name: "a cloud run",
      ctx: { cwd: "/repo", taskId: "task", taskRunId: "run" },
      meta: { environment: "cloud" as const },
      sandbox: true,
      exposed: true,
    },
    {
      name: "cloud metadata outside a sandbox",
      ctx: { cwd: "/repo", taskId: "task", taskRunId: "run" },
      meta: { environment: "cloud" as const },
      sandbox: false,
      exposed: false,
    },
    {
      name: "a local task",
      ctx: { cwd: "/repo", taskId: "task" },
      meta: { environment: "local" as const },
      sandbox: false,
      exposed: true,
    },
    {
      name: "a session without a task",
      ctx: { cwd: "/repo" },
      meta: { environment: "local" as const },
      sandbox: false,
      exposed: false,
    },
  ])(
    "is exposed for $name only when it can work",
    ({ ctx, meta, sandbox, exposed }) => {
      vi.stubEnv("IS_SANDBOX", sandbox ? "1" : "");
      const tools = enabledLocalTools(ctx, meta);
      expect(tools.some((t) => t.name === EXPOSE_PORT_TOOL_NAME)).toBe(exposed);
    },
  );

  it.each([80, 70000])("rejects port %i", (port) => {
    expect(exposePortSchema.port.safeParse(port).success).toBe(false);
  });

  it.each([
    { port: 8080, cloud: true, reserved: true },
    { port: 8080, cloud: false, reserved: false },
    { port: 5173, cloud: true, reserved: false },
  ])(
    "reserves port $port in a cloud sandbox only ($cloud)",
    ({ port, cloud, reserved }) => {
      expect(reservedPortProblem(port, cloud) !== null).toBe(reserved);
    },
  );

  it.each([
    {
      name: "no listener",
      open: new Set<string>(),
      expected: /Nothing listens on port 3000/,
    },
    {
      name: "a localhost-only listener",
      open: new Set(["127.0.0.1"]),
      expected: /bound to 0\.0\.0\.0/,
    },
    {
      name: "an IPv6 loopback-only listener",
      open: new Set(["::1"]),
      expected: /bound to 0\.0\.0\.0/,
    },
    {
      name: "a listener on all interfaces",
      open: new Set(["127.0.0.1", "10.0.0.2"]),
      expected: null,
    },
  ])("reports $name", async ({ open, expected }) => {
    const result = await checkListener(
      3000,
      async (host) => open.has(host),
      "10.0.0.2",
    );
    if (expected === null) {
      expect(result).toBeNull();
    } else {
      expect(result).toMatch(expected);
    }
  });
});
