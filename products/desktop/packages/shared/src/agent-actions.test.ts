import { describe, expect, it } from "vitest";
import { type AgentAction, buildActionUrl } from "./agent-actions";

describe("buildActionUrl", () => {
  const PROD = "posthog-code";
  const DEV = "posthog-code-dev";

  function parse(url: string): {
    protocol: string;
    host: string;
    pathname: string;
    params: URLSearchParams;
  } {
    const parsed = new URL(url);
    return {
      protocol: parsed.protocol,
      host: parsed.host,
      pathname: parsed.pathname,
      params: parsed.searchParams,
    };
  }

  describe("compose", () => {
    it("builds a new-task link with only the prompt when no repo is given", () => {
      expect(
        buildActionUrl({ kind: "compose", prompt: "Fix the login bug" }, PROD),
      ).toBe("posthog-code://new?prompt=Fix%20the%20login%20bug");
    });

    it("appends the repo when one is given", () => {
      expect(
        buildActionUrl(
          {
            kind: "compose",
            prompt: "Fix the login bug",
            repo: "posthog/posthog",
          },
          PROD,
        ),
      ).toBe(
        "posthog-code://new?prompt=Fix%20the%20login%20bug&repo=posthog%2Fposthog",
      );
    });

    it("appends trusted attribution for a resulting task", () => {
      const url = buildActionUrl({ kind: "compose", prompt: "Fix it" }, PROD, {
        action_id: "task:tool:0",
        source_task_id: "task",
        tool_call_id: "tool",
        action_index: 0,
      });

      const { params } = parse(url);
      expect(params.get("agent_action_id")).toBe("task:tool:0");
      expect(params.get("agent_action_source_task_id")).toBe("task");
      expect(params.get("agent_action_tool_call_id")).toBe("tool");
      expect(params.get("agent_action_index")).toBe("0");
    });

    it.each<[string, string]>([
      ["ampersand and query separators", "Ship A & B? #now"],
      ["a plus sign", "Bump limit from 1+1 to 3"],
      ["an injected extra parameter", "hi&repo=evil/repo"],
      ["a scheme-looking string", "go to https://evil.example/?x=1#f"],
      ["newlines and quotes", 'Line one\nLine "two"'],
    ])("round-trips a prompt containing %s", (_label, prompt) => {
      const url = buildActionUrl({ kind: "compose", prompt }, PROD);

      const { protocol, host, params } = parse(url);
      expect(protocol).toBe("posthog-code:");
      expect(host).toBe("new");
      expect(params.get("prompt")).toBe(prompt);
      expect(params.get("repo")).toBeNull();
    });

    it("round-trips a repo containing characters that need encoding", () => {
      const repo = "posthog/pos hog+1&x";
      const url = buildActionUrl(
        { kind: "compose", prompt: "Do it", repo },
        PROD,
      );

      expect(parse(url).params.get("repo")).toBe(repo);
    });
  });

  describe("open_space", () => {
    it("builds the channel link", () => {
      expect(
        buildActionUrl(
          {
            kind: "open_space",
            channel_id: "019ebc38-d862-77f2-9e56-c5ec42965758",
          },
          PROD,
        ),
      ).toBe("posthog-code://channel/019ebc38-d862-77f2-9e56-c5ec42965758");
    });

    it("percent-encodes the channel id so it cannot add path segments", () => {
      const url = buildActionUrl(
        { kind: "open_space", channel_id: "a/../b?c#d" },
        PROD,
      );

      expect(url).toBe("posthog-code://channel/a%2F..%2Fb%3Fc%23d");
      expect(decodeURIComponent(parse(url).pathname.slice(1))).toBe(
        "a/../b?c#d",
      );
    });
  });

  describe("open_canvas", () => {
    it("builds the two-segment canvas link", () => {
      expect(
        buildActionUrl(
          {
            kind: "open_canvas",
            channel_id: "019ebc38-d862-77f2-9e56-c5ec42965758",
            canvas_id: "dash_abc123",
          },
          PROD,
        ),
      ).toBe(
        "posthog-code://canvas/019ebc38-d862-77f2-9e56-c5ec42965758/dash_abc123",
      );
    });

    it("percent-encodes both ids so neither can add path segments", () => {
      const url = buildActionUrl(
        {
          kind: "open_canvas",
          channel_id: "chan/1?x",
          canvas_id: "canvas/2#y",
        },
        PROD,
      );

      expect(url).toBe("posthog-code://canvas/chan%2F1%3Fx/canvas%2F2%23y");
      const segments = parse(url).pathname.slice(1).split("/");
      expect(segments.map((segment) => decodeURIComponent(segment))).toEqual([
        "chan/1?x",
        "canvas/2#y",
      ]);
    });
  });

  describe("open_inbox", () => {
    it("builds the bare inbox link when no report is named", () => {
      expect(buildActionUrl({ kind: "open_inbox" }, PROD)).toBe(
        "posthog-code://inbox",
      );
    });

    it("builds the report link when one is named", () => {
      expect(
        buildActionUrl({ kind: "open_inbox", report_id: "rep_abc123" }, PROD),
      ).toBe("posthog-code://inbox/rep_abc123");
    });

    it("percent-encodes the report id so it cannot add path segments", () => {
      const url = buildActionUrl(
        { kind: "open_inbox", report_id: "a/../b?c#d" },
        PROD,
      );

      expect(url).toBe("posthog-code://inbox/a%2F..%2Fb%3Fc%23d");
      expect(decodeURIComponent(parse(url).pathname.slice(1))).toBe(
        "a/../b?c#d",
      );
    });
  });

  describe("dev scheme", () => {
    it.each<[string, AgentAction, string]>([
      [
        "compose",
        { kind: "compose", prompt: "Do it" },
        "posthog-code-dev://new?prompt=Do%20it",
      ],
      [
        "open_space",
        { kind: "open_space", channel_id: "chan" },
        "posthog-code-dev://channel/chan",
      ],
      [
        "open_canvas",
        { kind: "open_canvas", channel_id: "chan", canvas_id: "dash" },
        "posthog-code-dev://canvas/chan/dash",
      ],
      ["open_inbox", { kind: "open_inbox" }, "posthog-code-dev://inbox"],
      [
        "open_inbox with a report",
        { kind: "open_inbox", report_id: "rep" },
        "posthog-code-dev://inbox/rep",
      ],
    ])("uses the scheme it is given for %s", (_label, action, expected) => {
      expect(buildActionUrl(action, DEV)).toBe(expected);
    });
  });
});
