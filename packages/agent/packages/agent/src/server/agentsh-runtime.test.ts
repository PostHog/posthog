import { describe, expect, it, vi } from "vitest";
import {
  logAgentshRuntimeInfo,
  resolveAgentshRuntimeInfo,
} from "./agentsh-runtime";

describe("agentsh runtime detection", () => {
  it("returns null when no agentsh session marker exists", async () => {
    const getVersion = vi.fn();
    const result = await resolveAgentshRuntimeInfo({
      readSessionId: async () => {
        const error = new Error("missing") as NodeJS.ErrnoException;
        error.code = "ENOENT";
        throw error;
      },
      getVersion,
    });

    expect(result).toBeNull();
    expect(getVersion).not.toHaveBeenCalled();
  });

  it("rethrows unexpected session marker read errors", async () => {
    const error = new Error("permission denied") as NodeJS.ErrnoException;
    error.code = "EACCES";

    await expect(
      resolveAgentshRuntimeInfo({
        readSessionId: async () => {
          throw error;
        },
      }),
    ).rejects.toBe(error);
  });

  it.each([
    {
      name: "returns the agentsh session id and version",
      getVersion: async () => ({
        stdout: "agentsh version 0.18.3\n",
        stderr: "",
      }),
      expected: {
        sessionId: "session-123",
        version: "agentsh version 0.18.3",
      },
    },
    {
      name: "keeps the agentsh signal when version lookup fails",
      getVersion: async () => {
        throw new Error("agentsh not found");
      },
      expected: {
        sessionId: "session-123",
        version: null,
        versionLookupError: "agentsh not found",
      },
    },
  ])("$name", async ({ getVersion, expected }) => {
    const result = await resolveAgentshRuntimeInfo({
      readSessionId: async () => "session-123\n",
      getVersion,
    });

    expect(result).toEqual(expected);
  });

  it("logs session id and version details", async () => {
    const logger = { debug: vi.fn() };

    await logAgentshRuntimeInfo(logger, {
      readSessionId: async () => "session-123\n",
      getVersion: async () => ({
        stdout: "agentsh version 0.18.3\n",
        stderr: "",
      }),
    });

    expect(logger.debug).toHaveBeenCalledWith(
      "Agentsh session ID: session-123",
    );
    expect(logger.debug).toHaveBeenCalledWith(
      "Agentsh hardening version: agentsh version 0.18.3",
    );
  });

  it("logs version lookup failures", async () => {
    const logger = { debug: vi.fn() };

    await logAgentshRuntimeInfo(logger, {
      readSessionId: async () => "session-123\n",
      getVersion: async () => {
        throw new Error("agentsh not found");
      },
    });

    expect(logger.debug).toHaveBeenCalledWith(
      "Agentsh session ID: session-123",
    );
    expect(logger.debug).toHaveBeenCalledWith(
      "Agentsh hardening version: unknown",
    );
    expect(logger.debug).toHaveBeenCalledWith(
      "Agentsh version lookup failed: agentsh not found",
    );
  });
});
