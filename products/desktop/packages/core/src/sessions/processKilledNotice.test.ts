import { describe, expect, it } from "vitest";
import { formatProcessKilledNotice } from "./processKilledNotice";

describe("formatProcessKilledNotice", () => {
  it.each([
    {
      name: "full params → rendered notice",
      params: {
        pid: 4242,
        comm: "vitest",
        treeRssBytes: 13.46 * 1024 ** 3,
        memoryCurrentBytes: 15 * 1024 ** 3,
        memoryLimitBytes: 16 * 1024 ** 3,
        signal: "SIGTERM",
        at: "2026-01-01T00:00:00.000Z",
      },
      expected:
        "The sandbox stopped vitest because it was using 13.5 GiB of the 16.0 GiB available. The agent is still running.",
    },
    {
      name: "missing sizes → null",
      params: { comm: "vitest" },
      expected: null,
    },
    {
      name: "empty comm → null",
      params: { comm: "", treeRssBytes: 1, memoryLimitBytes: 2 },
      expected: null,
    },
    {
      name: "non-finite treeRssBytes → null",
      params: {
        comm: "vitest",
        treeRssBytes: Number.POSITIVE_INFINITY,
        memoryLimitBytes: 16 * 1024 ** 3,
      },
      expected: null,
    },
    {
      name: "non-finite memoryLimitBytes → null",
      params: {
        comm: "vitest",
        treeRssBytes: 1 * 1024 ** 3,
        memoryLimitBytes: Number.NaN,
      },
      expected: null,
    },
    { name: "undefined params → null", params: undefined, expected: null },
  ])("$name", ({ params, expected }) => {
    expect(formatProcessKilledNotice(params)).toBe(expected);
  });
});
