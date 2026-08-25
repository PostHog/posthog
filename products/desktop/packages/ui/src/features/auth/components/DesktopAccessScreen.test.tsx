import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DesktopAccessScreen } from "./DesktopAccessScreen";

const orgProjectsMap = {
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

function renderScreen(
  access:
    | {
        projectId: number;
        status: "blocked";
        reason: "startup_plan" | "prepaid_credits" | null;
      }
    | { projectId: number; status: "error"; reason: null },
) {
  const onSelectOrganization = vi.fn();
  const onSelectProject = vi.fn();
  const onRedeemInviteCode = vi.fn();
  const onRetry = vi.fn();
  const onLogout = vi.fn();
  const onOpenSupport = vi.fn();
  const result = render(
    <DesktopAccessScreen
      access={access}
      orgProjectsMap={orgProjectsMap}
      currentOrgId="org-1"
      currentProjectId={1}
      isSwitching={false}
      isRetrying={false}
      isRedeemingInviteCode={false}
      isLoggingOut={false}
      switchError={null}
      redemptionError={null}
      onSelectOrganization={onSelectOrganization}
      onSelectProject={onSelectProject}
      onRedeemInviteCode={onRedeemInviteCode}
      onRetry={onRetry}
      onLogout={onLogout}
      onOpenSupport={onOpenSupport}
    />,
  );
  return {
    ...result,
    onSelectOrganization,
    onSelectProject,
    onRedeemInviteCode,
    onRetry,
    onLogout,
    onOpenSupport,
  };
}

describe("DesktopAccessScreen", () => {
  it.each([
    ["startup_plan", "Organizations in the Startup or YC program"],
    ["prepaid_credits", "sales@posthog.com"],
  ] as const)("renders the %s reason", (reason, expectedCopy) => {
    renderScreen({ projectId: 1, status: "blocked", reason });

    expect(screen.getByText(new RegExp(expectedCopy))).toBeInTheDocument();
    expect(screen.getByText("First organization")).toBeInTheDocument();
    expect(screen.getByText("Website")).toBeInTheDocument();
  });

  it("preserves invite-code redemption for a legacy denial", async () => {
    const user = userEvent.setup();
    const { onRedeemInviteCode } = renderScreen({
      projectId: 1,
      status: "blocked",
      reason: null,
    });

    expect(screen.getByText("Enter your invite code")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Invite code"), "INVITE");
    await user.click(screen.getByText("Redeem invite code"));

    expect(onRedeemInviteCode).toHaveBeenCalledWith("INVITE");
  });

  it.each([
    [{ projectId: 1, status: "error", reason: null }, "Try again"],
    [
      { projectId: 1, status: "blocked", reason: "startup_plan" },
      "Check again",
    ],
  ] as const)("rechecks access for %s", async (access, buttonLabel) => {
    const user = userEvent.setup();
    const { onRetry } = renderScreen(access);

    await user.click(screen.getByText(buttonLabel));

    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("lets the user select another project", async () => {
    const user = userEvent.setup();
    const { container, onSelectProject } = renderScreen({
      projectId: 1,
      status: "blocked",
      reason: "startup_plan",
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
    const { container, onSelectOrganization, onLogout, onOpenSupport } =
      renderScreen({
        projectId: 1,
        status: "blocked",
        reason: "prepaid_credits",
      });
    const trigger = container.querySelector(
      '[data-attr="desktop-access-organization-switcher"]',
    );
    expect(trigger).not.toBeNull();

    await user.click(trigger as HTMLElement);
    await user.click(await screen.findByText("Second organization"));
    await user.click(screen.getByText("Get support"));
    await user.click(screen.getByText("Log out"));

    expect(onSelectOrganization).toHaveBeenCalledWith("org-2");
    expect(onOpenSupport).toHaveBeenCalledOnce();
    expect(onLogout).toHaveBeenCalledOnce();
  });
});
