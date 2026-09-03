import { describe, expect, it } from "vitest";
import { userDisplayName } from "./userDisplay";

describe("userDisplayName", () => {
  it.each([
    ["a missing user", null, "Unknown"],
    [
      "a full name",
      { first_name: "Ada", last_name: "Lovelace", email: "ada@example.com" },
      "Ada Lovelace",
    ],
    [
      "a first name only",
      { first_name: "Ada", email: "ada@example.com" },
      "Ada",
    ],
    ["an email only", { email: "ada@example.com" }, "ada@example.com"],
    [
      "empty name fields and no email",
      { first_name: "", last_name: "" },
      "Unknown",
    ],
  ])("renders %s", (_label, user, expected) => {
    expect(userDisplayName(user)).toBe(expected);
  });
});
