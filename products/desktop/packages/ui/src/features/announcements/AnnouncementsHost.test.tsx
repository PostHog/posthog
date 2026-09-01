import type { Announcement } from "@posthog/shared/announcements";
import { useUpdateInterruptStore } from "@posthog/ui/features/updates/updateInterruptStore";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnnouncementsHost } from "./AnnouncementsHost";
import type { ActiveAnnouncement } from "./selectAnnouncement";
import { useActiveAnnouncement } from "./useActiveAnnouncement";

vi.mock("./useActiveAnnouncement", () => ({
  useActiveAnnouncement: vi.fn(),
}));
vi.mock("./RequiredUpdateModal", () => ({
  RequiredUpdateModal: () => <div>required-update-modal</div>,
}));
vi.mock("./AnnouncementModal", () => ({
  AnnouncementModal: () => <div>announcement-modal</div>,
}));

const mockUseActiveAnnouncement = vi.mocked(useActiveAnnouncement);

const base = { id: "a1", title: "Title", body: "Body" };
const requiredUpdate = {
  ...base,
  kind: "required-update",
  minVersion: "9.9.9",
} as Announcement;
const blockingModal = {
  ...base,
  kind: "announcement",
  style: "modal",
  requiresAck: true,
} as Announcement;
const nonBlockingModal = {
  ...base,
  kind: "announcement",
  style: "modal",
  requiresAck: false,
} as Announcement;

function setActive(announcement: Announcement): void {
  mockUseActiveAnnouncement.mockReturnValue({
    announcement,
    needsUpdate: true,
  } as ActiveAnnouncement);
}

describe("AnnouncementsHost", () => {
  beforeEach(() => {
    mockUseActiveAnnouncement.mockReset();
    useUpdateInterruptStore.setState({
      isOpen: false,
      waitingForIdle: false,
      runInstall: null,
    });
  });

  // A blocking modal traps the whole app; if it stayed on stage during an
  // armed "restart when finished" wait, agents could never reach idle and the
  // wait would never complete.
  it.each([
    ["required-update", requiredUpdate, "required-update-modal"],
    ["blocking modal announcement", blockingModal, "announcement-modal"],
  ])(
    "hides the %s while a restart wait is armed",
    (_label, announcement, text) => {
      setActive(announcement);

      render(<AnnouncementsHost />);
      expect(screen.getByText(text)).toBeTruthy();

      act(() => useUpdateInterruptStore.setState({ waitingForIdle: true }));
      expect(screen.queryByText(text)).toBeNull();
    },
  );

  it("keeps a non-blocking announcement visible while a restart wait is armed", () => {
    setActive(nonBlockingModal);
    useUpdateInterruptStore.setState({ waitingForIdle: true });

    render(<AnnouncementsHost />);

    expect(screen.getByText("announcement-modal")).toBeTruthy();
  });
});
