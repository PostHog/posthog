import { describe, expect, it, vi } from "vitest";

vi.mock("expo-speech-recognition", () => ({
  ExpoSpeechRecognitionModule: {},
  useSpeechRecognitionEvent: vi.fn(),
}));
vi.mock("react-native-reanimated", () => ({}));
vi.mock("@/components/Waveform", () => ({ RING: 96, SAMPLE_MS: 80 }));

import {
  applyResult,
  type Heard,
  joinHeard,
  recognitionLang,
  volumeToLevel,
} from "./dictation";

const result = (transcript: string, isFinal: boolean) => ({
  isFinal,
  results: [{ transcript, confidence: 0, segments: [] }],
});

describe("volumeToLevel", () => {
  it.each([
    [-2, 0],
    [0, 0],
    [1, 0],
    [4.5, 0.5],
    [8, 1],
    [10, 1],
  ])("maps volume %d to level %d", (volume, level) => {
    expect(volumeToLevel(volume)).toBeCloseTo(level);
  });
});

describe("applyResult", () => {
  const empty: Heard = { finals: [], interim: "" };

  it("replaces the interim text until a result is final", () => {
    const first = applyResult(empty, result("open the", false));
    const second = applyResult(first, result("open the pull request", false));
    expect(second).toEqual({ finals: [], interim: "open the pull request" });
  });

  it("moves a final result into finals and clears the interim text", () => {
    const partial = applyResult(empty, result("fix the bug", false));
    const done = applyResult(partial, result(" Fix the bug.", true));
    expect(done).toEqual({ finals: ["Fix the bug."], interim: "" });
  });

  it("ignores empty final results", () => {
    const heard: Heard = { finals: ["Hello."], interim: "and" };
    const event = { isFinal: true, results: [] };
    expect(applyResult(heard, event)).toEqual({
      finals: ["Hello."],
      interim: "",
    });
  });
});

describe("joinHeard", () => {
  it("joins finals and the interim text with single spaces", () => {
    expect(
      joinHeard({ finals: ["Fix the bug.", " Then ship it."], interim: "now" }),
    ).toBe("Fix the bug. Then ship it. now");
  });

  it("returns an empty string when nothing was heard", () => {
    expect(joinHeard({ finals: [], interim: "" })).toBe("");
  });
});

describe("recognitionLang", () => {
  it.each([
    ["en-US", "en-US"],
    ["de-DE", "de-DE"],
    ["en-GB-u-ca-gregory", "en-GB"],
    ["en", undefined],
    ["zh-Hans-CN", undefined],
    ["", undefined],
  ])("maps locale %j to %j", (locale, lang) => {
    expect(recognitionLang(locale)).toBe(lang);
  });
});
