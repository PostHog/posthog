import { render, screen } from "@testing-library/react";
import { act } from "react";
import { describe, expect, it } from "vitest";
import { ReviewerAvatar } from "./ReviewerAvatar";

describe("ReviewerAvatar", () => {
  it.each([
    ["a first and last name", { name: "Ben W.", email: null }, "BW"],
    [
      "a many-word name",
      { name: "Ada Byron King Lovelace", email: null },
      "AL",
    ],
    ["a single-word name", { name: "Cher", email: null }, "C"],
    ["no name, an email", { name: null, email: "ben@posthog.com" }, "BE"],
    ["no name and no email", { name: null, email: null }, "U"],
  ])("derives initials from %s", async (_label, props, expected) => {
    await act(async () => {
      render(<ReviewerAvatar seed="seed-1" {...props} />);
    });
    expect(screen.getByText(expected)).toBeTruthy();
  });
});
