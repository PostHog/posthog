import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  rememberAvatarImageStatus,
  rememberedAvatarImageStatus,
} from "./avatarImageStatus";

const PAST_RETRY_WINDOW_MS = 61_000;

describe("avatarImageStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("forgets an error once the retry window has passed", () => {
    rememberAvatarImageStatus("https://example.com/offline.png", "error");
    expect(rememberedAvatarImageStatus("https://example.com/offline.png")).toBe(
      "error",
    );

    vi.advanceTimersByTime(PAST_RETRY_WINDOW_MS);

    expect(
      rememberedAvatarImageStatus("https://example.com/offline.png"),
    ).toBeUndefined();
  });

  it("keeps remembering a loaded image past the error retry window", () => {
    rememberAvatarImageStatus("https://example.com/loaded.png", "loaded");

    vi.advanceTimersByTime(PAST_RETRY_WINDOW_MS);

    expect(rememberedAvatarImageStatus("https://example.com/loaded.png")).toBe(
      "loaded",
    );
  });
});
