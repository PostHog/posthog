import { describe, expect, it } from "vitest";
import { getUserInitials } from "./userInitials";

describe("getUserInitials", () => {
  it("returns uppercased first+last initials when both are set", () => {
    expect(getUserInitials({ first_name: "Charles", last_name: "Vien" })).toBe(
      "CV",
    );
  });

  it("uppercases lowercase names", () => {
    expect(getUserInitials({ first_name: "alice", last_name: "smith" })).toBe(
      "AS",
    );
  });

  it("returns the first initial when only first_name is set", () => {
    expect(getUserInitials({ first_name: "Charles" })).toBe("C");
  });

  it("returns the last initial when only last_name is set", () => {
    expect(getUserInitials({ last_name: "Vien" })).toBe("V");
  });

  it("falls back to the first two letters of the email local part", () => {
    expect(getUserInitials({ email: "charles.v@posthog.com" })).toBe("CH");
  });

  it("never pulls letters from the email domain", () => {
    expect(getUserInitials({ email: "1234@example.com" })).toBe("U");
  });

  it("skips non-letter chars when extracting from names", () => {
    expect(getUserInitials({ first_name: " 123Alice" })).toBe("A");
  });

  it("skips non-letter chars when extracting from email local part", () => {
    expect(getUserInitials({ email: "1.2_charles@posthog.com" })).toBe("CH");
  });

  it("handles astral-plane characters without producing lone surrogates", () => {
    // U+20BB7 ("𠮷") is encoded as a UTF-16 surrogate pair. The old
    // implementation used string[0], which returned only the high surrogate
    // and rendered as a garbled tofu char.
    expect(getUserInitials({ first_name: "𠮷田", last_name: "Smith" })).toBe(
      "𠮷S",
    );
  });

  it("handles accented characters", () => {
    expect(getUserInitials({ first_name: "Émile", last_name: "Über" })).toBe(
      "ÉÜ",
    );
  });

  it("returns 'U' for a null user", () => {
    expect(getUserInitials(null)).toBe("U");
  });

  it("returns 'U' for an undefined user", () => {
    expect(getUserInitials(undefined)).toBe("U");
  });

  it("returns 'U' when every field is an empty string", () => {
    expect(getUserInitials({ first_name: "", last_name: "", email: "" })).toBe(
      "U",
    );
  });

  it("returns 'U' when names have no letters and there is no email", () => {
    expect(getUserInitials({ first_name: "123" })).toBe("U");
  });

  it("returns 'U' when names have no letters and the email local part has no letters", () => {
    expect(
      getUserInitials({ first_name: "123", email: "456@example.com" }),
    ).toBe("U");
  });

  it("ignores null name fields and uses the email fallback", () => {
    expect(
      getUserInitials({
        first_name: null,
        last_name: null,
        email: "charles.v@posthog.com",
      }),
    ).toBe("CH");
  });
});
