import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useTeamSkills, openTaskInput } = vi.hoisted(() => ({
  useTeamSkills: vi.fn(),
  openTaskInput: vi.fn(),
}));

vi.mock("@posthog/ui/features/skills/useTeamSkills", () => ({
  useTeamSkills,
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTaskInput }));
vi.mock("@posthog/quill", () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" {...props}>
      {children}
    </button>
  ),
  DropdownMenu: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  DropdownMenuTrigger: ({ render }: { render: React.ReactElement }) => render,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DropdownMenuItem: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" {...props}>
      {children}
    </button>
  ),
}));

import { PrSkillMenu } from "./PrSkillMenu";

const prUrl = "https://github.com/PostHog/posthog/pull/42";

describe("PrSkillMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("puts pr-shepherd first and opens a prefilled cloud task", async () => {
    useTeamSkills.mockReturnValue({
      data: {
        available: true,
        skills: [
          { id: "1", name: "other-skill" },
          { id: "2", name: "pr-shepherd" },
        ],
      },
    });

    render(<PrSkillMenu prUrl={prUrl} />);

    expect(
      screen.getAllByRole("button").map((button) => button.textContent?.trim()),
    ).toEqual(["Run skill", "pr-shepherd", "other-skill"]);
    await userEvent.click(screen.getByRole("button", { name: "pr-shepherd" }));
    expect(openTaskInput).toHaveBeenCalledWith({
      initialPrompt: `Run the pr-shepherd skill from the PostHog skills store for this pull request: ${prUrl}`,
      initialCloudRepository: "PostHog/posthog",
    });
  });

  it("does not offer an action when team skills are unavailable", async () => {
    useTeamSkills.mockReturnValue({
      data: { available: false, skills: [] },
    });

    render(<PrSkillMenu prUrl={prUrl} />);

    expect(
      screen.getByRole("button", { name: "No team skills available" }),
    ).toBeDisabled();
    expect(openTaskInput).not.toHaveBeenCalled();
  });

  it("does not render for an invalid pull request URL", () => {
    useTeamSkills.mockReturnValue({ data: { available: true, skills: [] } });

    const { container } = render(
      <PrSkillMenu prUrl="https://example.com/other/pull/42" />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
