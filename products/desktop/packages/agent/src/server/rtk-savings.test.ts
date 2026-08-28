import { describe, expect, it, vi } from "vitest";
import { resolveRtkSavings, scrubbedGainEnv } from "./rtk-savings";

const GAIN_JSON = JSON.stringify({
  summary: {
    total_commands: 2,
    total_input: 502691,
    total_output: 5835,
    total_saved: 496856,
  },
});

function gain(stdout: string) {
  return vi.fn().mockResolvedValue(stdout);
}

describe("resolveRtkSavings", () => {
  it("parses the rtk gain summary", async () => {
    const runGain = gain(GAIN_JSON);

    await expect(
      resolveRtkSavings({
        resolveBinary: () => "/bundled/rtk",
        runGain,
      }),
    ).resolves.toEqual({
      totalCommands: 2,
      inputTokens: 502691,
      outputTokens: 5835,
      tokensSaved: 496856,
    });
    expect(runGain).toHaveBeenCalledWith("/bundled/rtk", expect.anything());
  });

  it.each([
    ["the binary is unavailable", undefined, GAIN_JSON],
    [
      "nothing was tracked",
      "/bundled/rtk",
      JSON.stringify({ summary: { total_commands: 0 } }),
    ],
    ["the output is malformed", "/bundled/rtk", "not json"],
    ["the summary is missing", "/bundled/rtk", JSON.stringify({ daily: [] })],
  ])("returns null when %s", async (_label, binary, stdout) => {
    const runGain = gain(stdout);

    await expect(
      resolveRtkSavings({ resolveBinary: () => binary, runGain }),
    ).resolves.toBeNull();
    if (!binary) expect(runGain).not.toHaveBeenCalled();
  });

  it("returns null when rtk gain fails", async () => {
    await expect(
      resolveRtkSavings({
        resolveBinary: () => "/bundled/rtk",
        runGain: vi.fn().mockRejectedValue(new Error("rtk failed")),
      }),
    ).resolves.toBeNull();
  });
});

describe("scrubbedGainEnv", () => {
  it("keeps platform paths without forwarding secrets", () => {
    expect(
      scrubbedGainEnv({
        PATH: "/usr/bin",
        HOME: "/home/posthog",
        RTK_DB_PATH: "/tmp/posthog-rtk.db",
        GITHUB_TOKEN: "secret",
        ANTHROPIC_API_KEY: "secret",
      }),
    ).toEqual({
      PATH: "/usr/bin",
      HOME: "/home/posthog",
      RTK_DB_PATH: "/tmp/posthog-rtk.db",
    });
  });
});
