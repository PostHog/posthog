import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { toast } from "@posthog/ui/primitives/toast";
import { beforeEach, describe, expect, it, vi } from "vitest";

const writeText = vi.fn();

vi.mock("@posthog/ui/utils/posthogLinks", () => ({
  inboxReportUrl: (reportId: string) =>
    `https://us.posthog.com/project/2/inbox/${reportId}`,
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("copyInboxReportLink", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    writeText.mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
  });

  it("copies the browser-accessible report URL", async () => {
    await copyInboxReportLink({ id: "report-1" });

    expect(writeText).toHaveBeenCalledWith(
      "https://us.posthog.com/project/2/inbox/report-1",
    );
    expect(toast.success).toHaveBeenCalledWith("Link copied");
  });
});
