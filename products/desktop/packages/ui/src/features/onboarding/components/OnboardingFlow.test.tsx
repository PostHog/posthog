import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  completeOnboarding: vi.fn(),
  shipIt: vi.fn(),
  openTaskInput: vi.fn(),
  captureException: vi.fn(),
}));

vi.mock("@posthog/ui/features/onboarding/hooks/useOnboardingFlow", () => ({
  useOnboardingFlow: () => ({
    currentStep: "install-cli",
    currentIndex: 0,
    activeSteps: ["install-cli"],
    direction: 1,
    isLastStep: true,
    finalActiveStepWasRemoved: false,
    next: vi.fn(),
    back: vi.fn(),
    consentSatisfied: true,
    consentRequirement: undefined,
    currentStepPending: false,
  }),
}));
vi.mock("@posthog/ui/features/onboarding/onboardingStore", () => ({
  useOnboardingStore: (selector: (state: unknown) => unknown) =>
    selector({
      completeOnboarding: mocks.completeOnboarding,
      resetOnboarding: vi.fn(),
    }),
}));
vi.mock("@posthog/ui/features/onboarding/components/InstallCliStep", () => ({
  InstallCliStep: ({ onNext }: { onNext: () => void }) => (
    <button type="button" onClick={() => onNext()}>
      Continue
    </button>
  ),
}));
vi.mock("@posthog/ui/features/onboarding/components/ConnectGitHubStep", () => ({
  ConnectGitHubStep: () => null,
}));
vi.mock("./ProjectSelectStep", () => ({ ProjectSelectStep: () => null }));
vi.mock("@posthog/ui/features/consent/ConsentStep", () => ({
  ConsentStep: () => null,
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: () => false,
}));
vi.mock("@posthog/ui/features/auth/useAuthMutations", () => ({
  useLogoutMutation: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: undefined }),
}));
vi.mock("@posthog/ui/features/integrations/useIntegrations", () => ({
  useUserGithubIntegrations: () => ({ data: [] }),
}));
vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: (selector: (state: unknown) => unknown) =>
    selector({ setLastUsedWorkspaceMode: vi.fn() }),
}));
vi.mock("@posthog/ui/primitives/confetti", () => ({ shipIt: mocks.shipIt }));
vi.mock("@posthog/ui/primitives/FullScreenLayout", () => ({
  FullScreenLayout: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@posthog/ui/primitives/ProductWordmark", () => ({
  ProductWordmark: () => null,
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTaskInput: mocks.openTaskInput,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({
  track: vi.fn(),
  captureException: mocks.captureException,
}));
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: { scope: () => ({ error: vi.fn(), info: vi.fn() }) },
}));

import { OnboardingFlow } from "./OnboardingFlow";

describe("OnboardingFlow completion", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("completes onboarding when the confetti or task input throws", async () => {
    mocks.shipIt.mockImplementation(() => {
      throw new Error("confetti failed");
    });
    mocks.openTaskInput.mockImplementation(() => {
      throw new Error("task input failed");
    });
    render(<OnboardingFlow />);

    await userEvent.click(screen.getByText("Continue"));

    expect(mocks.completeOnboarding).toHaveBeenCalledTimes(1);
    expect(mocks.captureException).toHaveBeenCalledTimes(2);
  });

  it("lets Continue retry after the store write fails", async () => {
    mocks.completeOnboarding.mockImplementationOnce(() => {
      throw new Error("store write failed");
    });
    render(<OnboardingFlow />);

    await userEvent.click(screen.getByText("Continue"));
    await userEvent.click(screen.getByText("Continue"));

    expect(mocks.completeOnboarding).toHaveBeenCalledTimes(2);
    expect(mocks.captureException).toHaveBeenCalledTimes(1);
  });
});
