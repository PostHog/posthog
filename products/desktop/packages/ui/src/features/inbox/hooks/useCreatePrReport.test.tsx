import type { SignalReport } from "@posthog/shared/types";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockRun = vi.hoisted(() => vi.fn());
const mockTakeOver = vi.hoisted(() => vi.fn());
const mockCheckPrerequisites = vi.hoisted(() => vi.fn());
const mockTrackAction = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner", () => ({
  useInboxCloudTaskRunner: () => ({
    run: mockRun,
    isRunning: false,
    checkPrerequisites: mockCheckPrerequisites,
  }),
}));
vi.mock("@posthog/ui/features/inbox/hooks/useTakeOverReportClaim", () => ({
  useTakeOverReportClaim: () => ({
    mutateAsync: mockTakeOver,
    isPending: false,
  }),
}));
vi.mock("@posthog/ui/features/inbox/hooks/useSignalTeamConfig", () => ({
  useSignalTeamConfig: () => ({ data: null }),
}));
vi.mock("@posthog/ui/features/auth/useMeQuery", () => ({
  useMeQuery: () => ({ data: { uuid: "me" } }),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: () => null,
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));

import { useCreatePrReport } from "./useCreatePrReport";

const teammateClaim: Pick<SignalReport, "assignee"> = {
  assignee: {
    kind: "user",
    task_id: null,
    claim_id: "claim-robin",
    user: { id: 2, uuid: "robin", first_name: "Robin" },
    responsible_user: null,
  },
};

function setup() {
  return renderHook(() =>
    useCreatePrReport({
      reportId: "report-1",
      reportTitle: "Checkout fails",
      cloudRepository: "posthog/posthog",
      claim: teammateClaim,
      trackAction: mockTrackAction,
    }),
  );
}

describe("useCreatePrReport", () => {
  beforeEach(() => {
    mockRun.mockReset().mockResolvedValue(true);
    mockTakeOver.mockReset();
    mockCheckPrerequisites.mockReset().mockReturnValue(true);
    mockTrackAction.mockReset();
  });

  // Starting on a teammate's claim without the takeover fails the run, or moves
  // their work without telling them.
  it.each([
    { name: "starts the run after the takeover", takeOverFails: false },
    {
      name: "does not start the run when the takeover fails",
      takeOverFails: true,
    },
  ])(
    "asks before it takes over a teammate's claim and $name",
    async ({ takeOverFails }) => {
      if (takeOverFails) {
        mockTakeOver.mockRejectedValue(new Error("409"));
      } else {
        mockTakeOver.mockResolvedValue({});
      }
      const { result } = setup();

      await act(() => result.current.createPrReport());
      expect(mockRun).not.toHaveBeenCalled();
      render(result.current.claimDialog);
      await act(async () => {
        fireEvent.click(screen.getByText("Take over and implement"));
      });

      expect(mockTakeOver).toHaveBeenCalledWith({
        reportId: "report-1",
        claimId: "claim-robin",
      });
      expect(mockRun).toHaveBeenCalledTimes(takeOverFails ? 0 : 1);
    },
  );

  // Counting create_pr when the dialog opens would count a cancelled dialog as a started run.
  it.each([
    { button: "Take over and implement", confirmed: true },
    { button: "Cancel", confirmed: false },
  ])(
    "counts create_pr only after the claim dialog is confirmed ($button)",
    async ({ button, confirmed }) => {
      mockTakeOver.mockResolvedValue({});
      const { result } = setup();

      await act(() => result.current.createPrReport());
      render(result.current.claimDialog);
      await act(async () => {
        fireEvent.click(screen.getByText(button));
      });

      expect(mockTrackAction).toHaveBeenCalledWith("claim_dialog", {
        claim_step: "take_over",
        starts_run: true,
        confirmed,
      });
      expect(
        mockTrackAction.mock.calls.filter(([action]) => action === "create_pr"),
      ).toEqual(
        confirmed
          ? [["create_pr", { has_feedback: false, claim_step: "take_over" }]]
          : [],
      );
    },
  );

  // A takeover for a run that cannot start would move the claim and notify the
  // holder for nothing.
  it("does not offer the takeover when the run would fail its own checks", async () => {
    mockCheckPrerequisites.mockReturnValue(false);
    const { result } = setup();

    await act(() => result.current.createPrReport());

    expect(result.current.claimDialog).toBeNull();
    expect(mockTakeOver).not.toHaveBeenCalled();
    expect(mockRun).not.toHaveBeenCalled();
  });
});
