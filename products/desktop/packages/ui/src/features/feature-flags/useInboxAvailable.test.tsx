import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useInboxAvailable } from "./useInboxAvailable";

const flags = vi.hoisted(() => ({
  channelReportsEnabled: false,
  reportsInboxEnabled: false,
}));

vi.mock("./useChannelReportsEnabled", () => ({
  useChannelReportsEnabled: () => flags.channelReportsEnabled,
}));

vi.mock("./useReportsInboxEnabled", () => ({
  useReportsInboxEnabled: () => flags.reportsInboxEnabled,
}));

describe("useInboxAvailable", () => {
  beforeEach(() => {
    flags.channelReportsEnabled = false;
    flags.reportsInboxEnabled = false;
  });

  it.each([
    { channelReports: false, reportsInbox: false, available: true },
    { channelReports: false, reportsInbox: true, available: true },
    { channelReports: true, reportsInbox: false, available: false },
    { channelReports: true, reportsInbox: true, available: true },
  ])(
    "is $available when channel reports are $channelReports and the reports inbox is $reportsInbox",
    ({ channelReports, reportsInbox, available }) => {
      flags.channelReportsEnabled = channelReports;
      flags.reportsInboxEnabled = reportsInbox;

      const { result } = renderHook(() => useInboxAvailable());

      expect(result.current).toBe(available);
    },
  );
});
