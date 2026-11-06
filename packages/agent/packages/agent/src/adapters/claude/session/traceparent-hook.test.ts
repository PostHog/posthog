import { describe, expect, it } from "vitest";
import {
  buildTraceparentHookSettingsJson,
  traceIdFromHookStderr,
} from "./traceparent-hook";

const NONCE = "0123456789abcdef";

describe("traceparent hook", () => {
  it.each([
    [
      "a valid traceparent",
      `traceparent:${NONCE}=00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01`,
      "0af76519-16cd-43dd-8448-eb211c80319c",
    ],
    [
      "a future traceparent version",
      `traceparent:${NONCE}=01-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01`,
      "0af76519-16cd-43dd-8448-eb211c80319c",
    ],
    [
      "a trailing newline",
      `traceparent:${NONCE}=00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01\n`,
      "0af76519-16cd-43dd-8448-eb211c80319c",
    ],
    [
      "the all-zero trace id the W3C spec reserves for 'no trace'",
      `traceparent:${NONCE}=00-00000000000000000000000000000000-b7ad6b7169203331-01`,
      null,
    ],
    ["an empty TRACEPARENT env", `traceparent:${NONCE}=`, null],
    ["a malformed value", `traceparent:${NONCE}=not-a-traceparent`, null],
    [
      "another hook echoing a valid traceparent without the session nonce",
      "traceparent=00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
      null,
    ],
    [
      "another hook guessing a wrong nonce",
      "traceparent:ffffffffffffffff=00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
      null,
    ],
    [
      "output that is not from this hook",
      "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
      null,
    ],
  ])("handles %s", (_case, stderr, expected) => {
    expect(traceIdFromHookStderr(stderr, NONCE)).toBe(expected);
  });

  it("accepts nothing when the session has no nonce", () => {
    expect(
      traceIdFromHookStderr(
        `traceparent:${NONCE}=00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01`,
        undefined,
      ),
    ).toBeNull();
  });

  it("declares a command hook that writes to stderr, never to model context", () => {
    const settings = JSON.parse(buildTraceparentHookSettingsJson(NONCE));
    const hook = settings.hooks.UserPromptSubmit[0].hooks[0];
    expect(hook.type).toBe("command");
    expect(hook.command).toContain("$TRACEPARENT");
    expect(hook.command).toContain(`traceparent:${NONCE}=`);
    // stdout of a UserPromptSubmit hook is injected into the model's context;
    // stderr is not. The command must redirect.
    expect(hook.command).toContain(">&2");
  });
});
