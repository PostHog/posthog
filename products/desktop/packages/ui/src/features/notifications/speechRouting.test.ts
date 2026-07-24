import { describe, expect, it } from "vitest";
import type { NotificationChannel } from "./routeNotification";
import {
  type SpeechGateSettings,
  type SpeechKind,
  type SpeechSource,
  shouldSpeak,
} from "./speechRouting";

const base: SpeechGateSettings = {
  enabled: true,
  needsInput: true,
  completion: true,
  progress: true,
  focusMode: "always",
};

describe("shouldSpeak", () => {
  it("is silent when the feature is disabled", () => {
    expect(
      shouldSpeak("needs_input", "agent", "native", {
        ...base,
        enabled: false,
      }),
    ).toBe(false);
  });

  it.each<[SpeechKind, keyof SpeechGateSettings]>([
    ["needs_input", "needsInput"],
    ["done", "completion"],
    ["progress", "progress"],
  ])("respects the per-kind toggle for %s", (kind, key) => {
    expect(
      shouldSpeak(kind, "agent", "native", { ...base, [key]: false }),
    ).toBe(false);
  });

  it("always speaks agent needs-input regardless of focus", () => {
    for (const channel of ["suppress", "toast", "native"] as const) {
      expect(
        shouldSpeak("needs_input", "agent", channel, {
          ...base,
          focusMode: "app_unfocused",
        }),
      ).toBe(true);
    }
  });

  it.each<[NotificationChannel, boolean]>([
    ["suppress", false],
    ["toast", true],
    ["native", true],
  ])(
    "backstop needs-input is silent only over the viewed task: channel %s -> %s",
    (channel, expected) => {
      expect(
        shouldSpeak("needs_input", "backstop", channel, {
          ...base,
          focusMode: "app_unfocused",
        }),
      ).toBe(expected);
    },
  );

  it("backstop done never plays over the viewed task, even in always mode", () => {
    expect(
      shouldSpeak("done", "backstop", "suppress", {
        ...base,
        focusMode: "always",
      }),
    ).toBe(false);
  });

  it.each<[SpeechSource, NotificationChannel, boolean]>([
    ["agent", "suppress", false],
    ["agent", "toast", true],
    ["agent", "native", true],
    ["backstop", "suppress", false],
    ["backstop", "toast", true],
    ["backstop", "native", true],
  ])(
    "unviewed_task: %s done on channel %s -> %s",
    (source, channel, expected) => {
      expect(
        shouldSpeak("done", source, channel, {
          ...base,
          focusMode: "unviewed_task",
        }),
      ).toBe(expected);
    },
  );

  it.each<[NotificationChannel, boolean]>([
    ["suppress", false],
    ["toast", false],
    ["native", true],
  ])("app_unfocused: channel %s -> %s", (channel, expected) => {
    expect(
      shouldSpeak("done", "agent", channel, {
        ...base,
        focusMode: "app_unfocused",
      }),
    ).toBe(expected);
  });

  it("always mode speaks agent lines on every channel", () => {
    for (const channel of ["suppress", "toast", "native"] as const) {
      expect(
        shouldSpeak("done", "agent", channel, { ...base, focusMode: "always" }),
      ).toBe(true);
    }
  });
});
