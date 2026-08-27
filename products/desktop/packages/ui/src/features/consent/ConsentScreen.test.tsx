import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-hotkeys-hook", () => ({ useHotkeys: vi.fn() }));

vi.mock("@posthog/ui/features/auth/useAuthMutations", () => ({
  useLogoutMutation: () => ({ isPending: false, mutate: vi.fn() }),
}));

vi.mock("@posthog/ui/features/auth/useOrgRole", () => ({
  useIsOrgAdmin: () => ({ isAdmin: false }),
}));

vi.mock("@posthog/ui/features/settings/SettingsDialog", () => ({
  openSettingsDialog: vi.fn(),
}));

vi.mock("@posthog/ui/features/sidebar/components/ProjectSwitcher", () => ({
  ProjectSwitcher: () => <button type="button">Example project</button>,
}));

vi.mock("@posthog/ui/primitives/FullScreenLayout", () => ({
  FullScreenLayout: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("./ConsentPanel", () => ({
  ConsentPanel: () => <div>Consent requirements</div>,
}));

vi.mock("./useOrgConsent", () => ({
  useOrgConsent: () => ({
    status: "resolved",
    organizationId: "org-id",
    needsAiConsent: false,
    needsBetaTerms: true,
    satisfied: false,
  }),
}));

import { ConsentScreen } from "./ConsentScreen";

describe("ConsentScreen", () => {
  it("keeps the selected project switcher available while consent blocks the app", () => {
    render(<ConsentScreen />);

    expect(
      screen.getByRole("button", { name: "Example project" }),
    ).toBeVisible();
    expect(screen.getByText("Consent requirements")).toBeVisible();
  });
});
