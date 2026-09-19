import type { DesktopAccess } from "@posthog/core/auth/schemas";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { DesktopAccessScreen } from "./DesktopAccessScreen";

const twoOrganizations = {
  "org-1": {
    orgName: "First organization",
    projects: [
      { id: 1, name: "Website" },
      { id: 2, name: "Mobile app" },
    ],
  },
  "org-2": {
    orgName: "Second organization",
    projects: [{ id: 3, name: "Product" }],
  },
};

const oneOrganization = {
  "org-1": {
    orgName: "Only organization",
    projects: [{ id: 1, name: "Website" }],
  },
};

function renderScreen(
  access: DesktopAccess,
  orgProjectsMap:
    | typeof twoOrganizations
    | typeof oneOrganization = twoOrganizations,
) {
  const handlers = {
    onSelectOrganization: vi.fn(),
    onSelectProject: vi.fn(),
    onRetry: vi.fn(),
    onLogout: vi.fn(),
    onOpenSupport: vi.fn(),
  };
  const props = {
    access,
    orgProjectsMap,
    currentOrgId: "org-1",
    currentProjectId: 1,
    isSwitching: false,
    isRetrying: false,
    isLoggingOut: false,
    switchError: null,
    ...handlers,
  };
  const result = render(<DesktopAccessScreen {...props} />);
  return {
    ...result,
    ...handlers,
    rerenderWith: (next: Partial<typeof props>) =>
      result.rerender(<DesktopAccessScreen {...props} {...next} />),
  };
}

const blocked = (
  reason: "startup_plan" | "prepaid_credits",
): DesktopAccess => ({ projectId: 1, status: "blocked", reason });

describe("DesktopAccessScreen", () => {
  it.each([
    ["startup_plan", "Organizations in the Startup or YC program"],
    ["prepaid_credits", "sales@posthog.com"],
  ] as const)("renders the %s reason", (reason, expectedCopy) => {
    const { container } = renderScreen(blocked(reason));

    expect(screen.getByText(new RegExp(expectedCopy))).toBeInTheDocument();
    expect(screen.getByText("First organization")).toBeInTheDocument();
    // The decision covers the organization, so a project switch cannot lift it.
    expect(
      container.querySelector('[data-attr="desktop-access-project-switcher"]'),
    ).toBeNull();
  });

  it.each([
    [
      { projectId: 1, status: "error", reason: null } as DesktopAccess,
      "Try again",
    ],
    [blocked("startup_plan"), "Check again"],
  ] as const)("rechecks access for %s", async (access, buttonLabel) => {
    const user = userEvent.setup();
    const { onRetry } = renderScreen(access);

    await user.click(screen.getByText(buttonLabel));

    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("lets the user select another project after a failed check", async () => {
    const user = userEvent.setup();
    const { container, onSelectProject } = renderScreen({
      projectId: 1,
      status: "error",
      reason: null,
    });
    const trigger = container.querySelector(
      '[data-attr="desktop-access-project-switcher"]',
    );
    expect(trigger).not.toBeNull();

    await user.click(trigger as HTMLElement);
    await user.click(await screen.findByText("Mobile app"));

    expect(onSelectProject).toHaveBeenCalledWith(2);
  });

  it("lets the user select another organization and log out", async () => {
    const user = userEvent.setup();
    const { container, onSelectOrganization, onLogout } = renderScreen(
      blocked("prepaid_credits"),
    );
    const trigger = container.querySelector(
      '[data-attr="desktop-access-organization-switcher"]',
    );
    expect(trigger).not.toBeNull();

    await user.click(trigger as HTMLElement);
    await user.click(await screen.findByText("Second organization"));
    await user.click(screen.getByText("Log out"));

    expect(onSelectOrganization).toHaveBeenCalledWith("org-2");
    expect(onLogout).toHaveBeenCalledOnce();
  });

  it("offers support instead of a switcher when the account has one organization", async () => {
    const user = userEvent.setup();
    const { container, onOpenSupport } = renderScreen(
      blocked("startup_plan"),
      oneOrganization,
    );

    expect(
      screen.getByText(/only organization on your account/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Select another organization to continue."),
    ).toBeNull();
    expect(
      container.querySelector(
        '[data-attr="desktop-access-organization-switcher"]',
      ),
    ).toBeNull();

    await user.click(screen.getByText("Get in touch"));

    expect(onOpenSupport).toHaveBeenCalledOnce();
  });

  it("reports a recheck that returned the same answer", async () => {
    const { rerenderWith } = renderScreen(blocked("startup_plan"));
    expect(screen.queryByText(/nothing changed/)).toBeNull();

    rerenderWith({ isRetrying: true });
    rerenderWith({ isRetrying: false });

    expect(await screen.findByText(/nothing changed/)).toBeInTheDocument();
  });
});
