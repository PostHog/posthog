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

vi.mock("@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner", () => ({
  useInboxCloudTaskRunner: () => ({ run: mockRun, isRunning: false }),
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
    }),
  );
}

describe("useCreatePrReport", () => {
  beforeEach(() => {
    mockRun.mockReset().mockResolvedValue(true);
    mockTakeOver.mockReset();
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
});
