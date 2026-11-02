import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import {
  markReadOptimistically,
  restoreReadState,
  summarizeReadStates,
} from "./reportReadState";

describe("reportReadState", () => {
  it("counts only a fresh, successful false as unread", () => {
    const states = summarizeReadStates(
      ["read", "unread", "failed", "cached", "stale-after-error"],
      [
        { data: true, isError: false, isFetchedAfterMount: true },
        { data: false, isError: false, isFetchedAfterMount: true },
        { data: undefined, isError: true, isFetchedAfterMount: true },
        { data: false, isError: false, isFetchedAfterMount: false },
        { data: false, isError: true, isFetchedAfterMount: true },
      ],
    );
    expect([...states.unread]).toEqual(["unread"]);
  });

  it("is not settled while a cached state waits for the server", () => {
    const states = summarizeReadStates(
      ["a", "b"],
      [
        { data: false, isError: false, isFetchedAfterMount: false },
        { data: true, isError: false, isFetchedAfterMount: true },
      ],
    );
    expect(states.settled).toBe(false);
  });

  it.each([
    [false, false],
    [undefined, undefined],
  ])(
    "puts back %s after a failed write so the next open retries",
    async (previous, restored) => {
      const queryClient = new QueryClient();
      const key = ["reports", "read", "r"];
      if (previous !== undefined) queryClient.setQueryData(key, previous);

      const saved = await markReadOptimistically(queryClient, key);
      expect(queryClient.getQueryData(key)).toBe(true);

      await restoreReadState(queryClient, key, saved);
      expect(queryClient.getQueryData(key)).toBe(restored);
    },
  );
});
