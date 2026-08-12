import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeReauthPrompt } from "./ScopeReauthPrompt";

const authState = {
  status: "anonymous" as const,
  bootstrapComplete: true,
  cloudRegion: null as "us" | "eu" | "dev" | null,
  orgProjectsMap: {} as Record<
    string,
    { orgName: string; projects: { id: number; name: string }[] }
  >,
  currentOrgId: null as string | null,
  currentProjectId: null as number | null,
  hasCodeAccess: null,
  needsScopeReauth: false,
};

const mockLoginMutateAsync = vi.fn();
const mockLogoutMutate = vi.fn(() => {
  authState.needsScopeReauth = false;
  authState.cloudRegion = null;
});

vi.mock("../store", () => ({
  useAuthStateValue: (selector: (state: typeof authState) => unknown) =>
    selector(authState),
}));

vi.mock("../useAuthMutations", () => ({
  useLoginMutation: () => ({
    mutateAsync: mockLoginMutateAsync,
    isPending: false,
  }),
  useLogoutMutation: () => ({
    mutate: mockLogoutMutate,
  }),
}));

vi.mock("../../../shell/logger", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

function renderWithTheme(ui: ReactElement) {
  return render(<Theme>{ui}</Theme>);
}

describe("ScopeReauthPrompt", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.status = "anonymous";
    authState.cloudRegion = null;
    authState.currentProjectId = null;
    authState.hasCodeAccess = null;
    authState.needsScopeReauth = false;
  });

  it("does not render dialog when needsScopeReauth is false", () => {
    renderWithTheme(<ScopeReauthPrompt />);
    expect(
      screen.queryByText("Re-authentication required"),
    ).not.toBeInTheDocument();
  });

  it("renders dialog when needsScopeReauth is true", () => {
    authState.needsScopeReauth = true;
    authState.cloudRegion = "us";

    renderWithTheme(<ScopeReauthPrompt />);

    expect(screen.getByText("Re-authentication required")).toBeInTheDocument();
  });

  it("disables Sign in button when cloudRegion is null", () => {
    authState.needsScopeReauth = true;

    renderWithTheme(<ScopeReauthPrompt />);

    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  });

  it("enables Sign in button when cloudRegion is set", () => {
    authState.needsScopeReauth = true;
    authState.cloudRegion = "us";

    renderWithTheme(<ScopeReauthPrompt />);

    expect(screen.getByRole("button", { name: "Sign in" })).not.toBeDisabled();
  });

  it("shows Log out button as an escape hatch when cloudRegion is null", () => {
    authState.needsScopeReauth = true;

    renderWithTheme(<ScopeReauthPrompt />);

    const logoutButton = screen.getByRole("button", { name: "Log out" });
    expect(logoutButton).toBeInTheDocument();
    expect(logoutButton).not.toBeDisabled();
  });

  it("calls logout when Log out button is clicked", async () => {
    const user = userEvent.setup();
    authState.needsScopeReauth = true;

    renderWithTheme(<ScopeReauthPrompt />);

    await user.click(screen.getByRole("button", { name: "Log out" }));

    expect(mockLogoutMutate).toHaveBeenCalledTimes(1);
    expect(authState.needsScopeReauth).toBe(false);
    expect(authState.cloudRegion).toBeNull();
  });
});
