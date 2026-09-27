import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePrSkillUsageStore } from "./prSkillUsageStore";

const { useTeamSkills, openTaskInput } = vi.hoisted(() => ({
  useTeamSkills: vi.fn(),
  openTaskInput: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: vi.fn(),
  useAuthStateValue: () => "project-1",
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: "user-1" } }),
}));
vi.mock("@posthog/ui/features/skills/useTeamSkills", () => ({
  useTeamSkills,
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTaskInput }));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: React.ReactNode }) => (
    <a href="/settings/skills">{children}</a>
  ),
}));

import { PrSkillMenu } from "./PrSkillMenu";

const prUrl = "https://github.com/PostHog/posthog/pull/42";
const scope = JSON.stringify(["project-1", "user-1"]);

describe("PrSkillMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    usePrSkillUsageStore.setState({ countsByScope: {} });
  });

  it("searches skills and opens a prefilled cloud task", async () => {
    const user = userEvent.setup();
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
    await user.click(screen.getByRole("combobox", { name: "Run skill" }));
    await user.type(
      await screen.findByPlaceholderText("Search team skills…"),
      "shepherd",
    );

    expect(screen.getByRole("option", { name: "pr-shepherd" })).toBeVisible();
    expect(
      screen.queryByRole("option", { name: "other-skill" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "pr-shepherd" }));
    expect(openTaskInput).toHaveBeenCalledWith({
      initialPrompt: `Run the pr-shepherd skill from the PostHog skills store for this pull request: ${prUrl}`,
      initialCloudRepository: "PostHog/posthog",
    });
    expect(usePrSkillUsageStore.getState().countsByScope[scope]).toEqual({
      "pr-shepherd": 1,
    });
    expect(localStorage.getItem("pr-skill-usage")).toContain("pr-shepherd");
  });

  it("shows frequent skills before the store loads and keeps them first when it does", async () => {
    const user = userEvent.setup();
    usePrSkillUsageStore.getState().recordChoice(scope, "z-skill");
    usePrSkillUsageStore.getState().recordChoice(scope, "z-skill");
    usePrSkillUsageStore.getState().recordChoice(scope, "a-skill");
    usePrSkillUsageStore
      .getState()
      .recordChoice(JSON.stringify(["project-2", "user-2"]), "private-skill");
    const savedChoices = localStorage.getItem("pr-skill-usage");
    if (!savedChoices) throw new Error("Skill choices were not saved");
    usePrSkillUsageStore.setState({ countsByScope: {} });
    localStorage.setItem("pr-skill-usage", savedChoices);
    await usePrSkillUsageStore.persist.rehydrate();
    useTeamSkills.mockReturnValue({ data: undefined, isLoading: true });

    const { rerender } = render(<PrSkillMenu prUrl={prUrl} />);
    await user.click(screen.getByRole("combobox", { name: "Run skill" }));
    expect(
      (await screen.findAllByRole("option")).map(
        (option) => option.textContent,
      ),
    ).toEqual(["z-skill", "a-skill"]);

    useTeamSkills.mockReturnValue({
      data: {
        available: true,
        skills: [
          { id: "1", name: "a-skill" },
          { id: "2", name: "z-skill" },
          { id: "3", name: "b-skill" },
        ],
      },
    });
    rerender(<PrSkillMenu prUrl={prUrl} />);
    expect(
      screen.getAllByRole("option").map((option) => option.textContent),
    ).toEqual(["z-skill", "a-skill", "b-skill"]);
  });

  it("links to the store when the team has no skills", async () => {
    useTeamSkills.mockReturnValue({
      data: { available: true, skills: [] },
    });

    render(<PrSkillMenu prUrl={prUrl} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Run skill" }));

    expect(await screen.findByText(/No team skills yet/)).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Explore the skills store" }),
    ).toHaveAttribute("href", "/settings/skills");
  });

  it("does not show removed store skills after the team list loads", async () => {
    usePrSkillUsageStore.getState().recordChoice(scope, "removed-skill");
    useTeamSkills.mockReturnValue({
      data: { available: true, skills: [{ id: "1", name: "other-skill" }] },
    });

    render(<PrSkillMenu prUrl={prUrl} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Run skill" }));

    expect(
      screen.queryByRole("option", { name: "removed-skill" }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("option", { name: "other-skill" }),
    ).toBeVisible();
  });

  it("does not render for an invalid pull request URL", () => {
    useTeamSkills.mockReturnValue({ data: { available: true, skills: [] } });

    const { container } = render(
      <PrSkillMenu prUrl="https://example.com/other/pull/42" />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
