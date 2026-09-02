import { describe, expect, it } from "vitest";
import { parseSessionIdArg } from "./posthog-session-arg";

describe("parseSessionIdArg", () => {
  it("returns the value when the flag is present", () => {
    expect(parseSessionIdArg(["--posthog-session-id=abc-123"])).toBe("abc-123");
  });

  it("finds the flag among other arguments", () => {
    expect(
      parseSessionIdArg(["--foo", "--posthog-session-id=xyz", "--bar"]),
    ).toBe("xyz");
  });

  it("returns null when the flag is absent", () => {
    expect(parseSessionIdArg(["--type=renderer", "--no-sandbox"])).toBeNull();
  });

  it("ignores arguments that only share the prefix", () => {
    expect(parseSessionIdArg(["--posthog-session-id-extra=foo"])).toBeNull();
  });

  it("returns an empty string when the flag has no value", () => {
    expect(parseSessionIdArg(["--posthog-session-id="])).toBe("");
  });
});
