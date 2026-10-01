import { ExpoSpeechRecognitionModule } from "expo-speech-recognition";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listeners = vi.hoisted(
  () => new Map<string, (event?: unknown) => void>(),
);

vi.mock("expo-speech-recognition", () => ({
  ExpoSpeechRecognitionModule: {
    requestPermissionsAsync: vi.fn(async () => ({ granted: true })),
    start: vi.fn(),
    stop: vi.fn(),
    abort: vi.fn(),
  },
  useSpeechRecognitionEvent: (
    name: string,
    listener: (event?: unknown) => void,
  ) => listeners.set(name, listener),
}));
vi.mock("react", () => ({
  useCallback: <T>(fn: T) => fn,
  useEffect: () => {},
  useRef: <T>(current: T) => ({ current }),
  useState: <T>(initial: T) => [initial, () => {}],
}));
vi.mock("react-native-reanimated", () => ({
  Easing: { linear: (t: number) => t },
  useSharedValue: <T>(value: T) => ({ value, modify: () => {} }),
  withTiming: (value: number) => value,
}));
vi.mock("@/components/Waveform", () => ({ RING: 96, SAMPLE_MS: 80 }));

import {
  applyResult,
  type Dictation,
  type Heard,
  joinHeard,
  recognitionLang,
  useDictation,
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

describe("useDictation", () => {
  const native = vi.mocked(ExpoSpeechRecognitionModule);

  beforeEach(() => {
    vi.clearAllMocks();
    listeners.clear();
  });

  const startNative = async (): Promise<Dictation> => {
    const dictation = useDictation();
    dictation.start();
    await vi.waitFor(() => expect(native.start).toHaveBeenCalledTimes(1));
    return dictation;
  };

  it.each([
    ["stop", (dictation: Dictation) => dictation.stop()],
    ["cancel", (dictation: Dictation) => dictation.cancel()],
  ])("aborts a native start that finishes after %s", async (_, end) => {
    end(await startNative());
    native.abort.mockClear();
    listeners.get("start")?.();
    expect(native.abort).toHaveBeenCalledTimes(1);
  });

  it("keeps a native start while dictation is active", async () => {
    await startNative();
    listeners.get("start")?.();
    expect(native.abort).not.toHaveBeenCalled();
  });

  it("ignores a native start that it did not request", () => {
    useDictation();
    listeners.get("start")?.();
    expect(native.abort).not.toHaveBeenCalled();
  });
});
