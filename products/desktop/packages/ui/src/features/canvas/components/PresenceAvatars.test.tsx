import type { UserBasic } from "@posthog/shared/domain-types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PresenceAvatar, PresenceAvatars } from "./PresenceAvatars";

function user(uuid: string, first: string): UserBasic {
  return {
    id: 1,
    uuid,
    email: `${first.toLowerCase()}@example.com`,
    first_name: first,
  };
}

describe("PresenceAvatars", () => {
  it("draws one labelled face per person", () => {
    render(<PresenceAvatars people={[user("a", "Ada"), user("b", "Bruno")]} />);
    expect(screen.getByRole("img", { name: "Ada" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Bruno" })).toBeTruthy();
  });

  it("marks the lead as the space creator", () => {
    render(<PresenceAvatars people={[user("a", "Ada")]} leadUuid="a" />);
    expect(
      screen.getByRole("img", { name: "Ada created this space" }),
    ).toBeTruthy();
  });

  it("renders nothing when there are no people", () => {
    const { container } = render(<PresenceAvatars people={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("PresenceAvatar", () => {
  it("labels a single owner face", () => {
    render(
      <PresenceAvatar
        user={user("a", "Ada")}
        tier="live"
        label="Ada is working on this"
      />,
    );
    expect(
      screen.getByRole("img", { name: "Ada is working on this" }),
    ).toBeTruthy();
  });
});
