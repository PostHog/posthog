import { describe, expect, it } from "vitest";
import { useSessionResyncStore } from "./sessionResyncStore";

describe("sessionResyncStore", () => {
  it("bumps per-task nonces independently", () => {
    const { bump } = useSessionResyncStore.getState();

    bump("task-1");
    bump("task-1");
    bump("task-2");

    const { nonces } = useSessionResyncStore.getState();
    expect(nonces["task-1"]).toBe(2);
    expect(nonces["task-2"]).toBe(1);
    expect(nonces["task-3"]).toBeUndefined();
  });
});
