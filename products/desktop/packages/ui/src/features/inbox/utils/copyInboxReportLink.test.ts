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

  it.each([
    [
      "web",
      "https://us.posthog.com/project/2/inbox/report-1",
      "Web link copied",
    ],
    [
      "desktop",
      "posthog-code-dev://inbox/report-1/Example-report",
      "Desktop link copied",
    ],
  ] as const)(
    "copies the %s report link",
    async (target, expectedUrl, successCopy) => {
      await copyInboxReportLink(
        { id: "report-1", title: "Example report" },
        target,
      );

      expect(writeText).toHaveBeenCalledWith(expectedUrl);
      expect(toast.success).toHaveBeenCalledWith(successCopy);
    },
  );
});
