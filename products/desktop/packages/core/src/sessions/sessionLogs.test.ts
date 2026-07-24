import { describe, expect, it, vi } from "vitest";
import { parseSessionLogContent } from "./sessionLogs";

describe("parseSessionLogContent", () => {
  it("parses one stored entry per line", () => {
    const content = [
      JSON.stringify({ type: "request", message: { id: 1 } }),
      JSON.stringify({ type: "notification", notification: { method: "x" } }),
    ].join("\n");

    const result = parseSessionLogContent(content);

    expect(result.rawEntries).toHaveLength(2);
    expect(result.totalLineCount).toBe(2);
    expect(result.parseFailureCount).toBe(0);
    expect(result.sessionId).toBeUndefined();
    expect(result.adapter).toBeUndefined();
  });

  it("extracts sessionId and adapter from a posthog/sdk_session notification", () => {
    const content = JSON.stringify({
      type: "notification",
      notification: {
        method: "_posthog/sdk_session",
        params: { sessionId: "sess-9", adapter: "codex" },
      },
    });

    const result = parseSessionLogContent(content);

    expect(result.sessionId).toBe("sess-9");
    expect(result.adapter).toBe("codex");
  });

  it("falls back to sdkSessionId when sessionId is absent", () => {
    const content = JSON.stringify({
      type: "notification",
      notification: {
        method: "agent/posthog/sdk_session",
        params: { sdkSessionId: "sdk-7" },
      },
    });

    expect(parseSessionLogContent(content).sessionId).toBe("sdk-7");
  });

  it("counts parse failures and invokes onParseError for each bad line", () => {
    const onParseError = vi.fn();
    const content = ["not json", JSON.stringify({ type: "request" })].join(
      "\n",
    );

    const result = parseSessionLogContent(content, { onParseError });

    expect(result.parseFailureCount).toBe(1);
    expect(result.rawEntries).toHaveLength(1);
    expect(onParseError).toHaveBeenCalledTimes(1);
    expect(onParseError).toHaveBeenCalledWith("not json");
  });
});
