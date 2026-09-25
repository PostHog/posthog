import { describe, expect, it } from "vitest";
import { enabledLocalTools } from "../index";
import {
  checkListener,
  EXPOSE_PORT_TOOL_NAME,
  exposePortSchema,
} from "./expose-port";

describe("expose_port tool", () => {
  it.each([
    {
      name: "a cloud run",
      meta: { environment: "cloud" as const },
      exposed: true,
    },
    {
      name: "a local session",
      meta: { environment: "local" as const },
      exposed: false,
    },
  ])("is exposed only in $name when expected", ({ meta, exposed }) => {
    const tools = enabledLocalTools(
      { cwd: "/repo", taskId: "task", taskRunId: "run" },
      meta,
    );
    expect(tools.some((t) => t.name === EXPOSE_PORT_TOOL_NAME)).toBe(exposed);
  });

  it.each([8080, 8181, 80, 70000])("rejects port %i", (port) => {
    expect(exposePortSchema.port.safeParse(port).success).toBe(false);
  });

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
