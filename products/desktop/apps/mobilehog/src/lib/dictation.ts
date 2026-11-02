import {
  ExpoSpeechRecognitionModule,
  type ExpoSpeechRecognitionResultEvent,
  useSpeechRecognitionEvent,
} from "expo-speech-recognition";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Easing,
  type SharedValue,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { RING, SAMPLE_MS } from "@/components/Waveform";

export interface Dictation {
  // Stays true while a stop waits for the final result.
  active: boolean;
  stopping: boolean;
  transcript: string;
  // Read on the UI thread by the waveform; updating them never re-renders React.
  levels: SharedValue<number[]>;
  head: SharedValue<number>;
  start: () => void;
  // Ends dictation and resolves with what was heard once the recognizer delivers its final result.
  // A second call during the wait resolves with "", so each caller gets the words only once.
  // Resolves with null when cancel ends the wait.
  stop: () => Promise<string | null>;
  // Ends dictation and drops what was heard.
  cancel: () => void;
}

export interface Heard {
  finals: string[];
  interim: string;
}

// The recognizer reports volume from -2 to 10; below QUIET is room noise.
const QUIET = 1;
const LOUD = 8;
// Safety net for a recognizer that never reports end after stop.
const STOP_TIMEOUT_MS = 1500;

export function volumeToLevel(value: number): number {
  return Math.min(1, Math.max(0, (value - QUIET) / (LOUD - QUIET)));
}

export function applyResult(
  heard: Heard,
  event: ExpoSpeechRecognitionResultEvent,
): Heard {
  const text = event.results[0]?.transcript.trim() ?? "";
  if (!event.isFinal) return { finals: heard.finals, interim: text };
  return { finals: text ? [...heard.finals, text] : heard.finals, interim: "" };
}

export function joinHeard({ finals, interim }: Heard): string {
  return [...finals, interim]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ");
}

// Recognizers name locales by language and region, so a script subtag is dropped: zh-Hans-CN becomes zh-CN.
// Any other shape returns undefined, and the recognizer then uses its en-US default.
export function recognitionLang(locale: string): string | undefined {
  const match = /^([a-z]{2,3})(?:-[A-Z][a-z]{3})?(-[A-Z]{2})(?:-u-|$)/.exec(
    locale,
  );
  return match ? match[1] + match[2] : undefined;
}

const emptyRing = (): number[] => new Array(RING).fill(-1);
const nothingHeard = (): Heard => ({ finals: [], interim: "" });

// onEnd receives what was heard when the recognizer ends on its own.
export function useDictation(onEnd?: (heard: string) => void): Dictation {
  const [active, setActive] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [transcript, setTranscript] = useState("");
  const levels = useSharedValue<number[]>(emptyRing());
  const head = useSharedValue(-1);
  const count = useRef(0);
  const heard = useRef<Heard>(nothingHeard());
  // Bumped on every start and finish so a late permission answer cannot restart a finished session.
  const session = useRef(0);
  const live = useRef(false);
  const listening = useRef(false);
  // True from this hook's native start call until the recognizer reports start or a startup error.
  const starting = useRef(false);
  const pendingStop = useRef<((heard: string | null) => void) | null>(null);
  const stopTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const endRef = useRef(onEnd);

  useEffect(() => {
    endRef.current = onEnd;
  }, [onEnd]);

  const push = useCallback(
    (level: number) => {
      const id = count.current++;
      levels.modify((ring) => {
        "worklet";
        ring[id % RING] = level;
        return ring;
      });
      head.value = withTiming(id, {
        duration: SAMPLE_MS,
        easing: Easing.linear,
      });
    },
    [levels, head],
  );

  const finish = useCallback((kept: string | null = ""): boolean => {
    const wasListening = listening.current;
    const resolve = pendingStop.current;
    session.current++;
    live.current = false;
    listening.current = false;
    pendingStop.current = null;
    clearTimeout(stopTimer.current);
    setStopping(false);
    setActive(false);
    resolve?.(kept);
    return wasListening;
  }, []);

  // Before native start, an end or error can only come from the previous session.
  const endQuietly = useCallback(() => {
    if (!live.current || !listening.current) return;
    const text = joinHeard(heard.current);
    if (pendingStop.current) {
      finish(text);
      return;
    }
    finish();
    endRef.current?.(text);
  }, [finish]);

  useSpeechRecognitionEvent("volumechange", (event) => {
    if (live.current) push(volumeToLevel(event.value));
  });

  useSpeechRecognitionEvent("result", (event) => {
    if (!live.current) return;
    heard.current = applyResult(heard.current, event);
    setTranscript(joinHeard(heard.current));
  });

  // On iOS, native start runs in a task that stop and abort do not wait for.
  // A stop or cancel during startup can finish first, and the microphone then opens after dictation ended.
  useSpeechRecognitionEvent("start", () => {
    if (!starting.current) return;
    starting.current = false;
    if (!live.current || pendingStop.current) {
      ExpoSpeechRecognitionModule.abort();
    }
  });

  useSpeechRecognitionEvent("error", (event) => {
    if (event.error === "aborted") return;
    starting.current = false;
    endQuietly();
  });

  useSpeechRecognitionEvent("end", endQuietly);

  useEffect(
    () => () => {
      session.current++;
      live.current = false;
      clearTimeout(stopTimer.current);
      if (listening.current || starting.current) {
        ExpoSpeechRecognitionModule.abort();
      }
    },
    [],
  );

  const start = useCallback(() => {
    const id = ++session.current;
    count.current = 0;
    levels.value = emptyRing();
    head.value = -1;
    heard.current = nothingHeard();
    live.current = true;
    listening.current = false;
    setTranscript("");
    setActive(true);
    ExpoSpeechRecognitionModule.requestPermissionsAsync()
      .then((permission) => {
        if (id !== session.current) return;
        if (!permission.granted) {
          finish();
          return;
        }
        listening.current = true;
        starting.current = true;
        ExpoSpeechRecognitionModule.start({
          lang: recognitionLang(Intl.DateTimeFormat().resolvedOptions().locale),
          interimResults: true,
          continuous: true,
          addsPunctuation: true,
          volumeChangeEventOptions: {
            enabled: true,
            intervalMillis: SAMPLE_MS,
          },
        });
      })
      .catch(() => {
        if (id === session.current) finish();
      });
  }, [levels, head, finish]);

  // Results keep arriving after native stop, so the session stays live until the recognizer reports end.
  const stop = useCallback((): Promise<string | null> => {
    if (!live.current || pendingStop.current) return Promise.resolve("");
    if (!listening.current) {
      finish();
      return Promise.resolve(joinHeard(heard.current));
    }
    const done = new Promise<string | null>((resolve) => {
      pendingStop.current = resolve;
    });
    stopTimer.current = setTimeout(() => {
      if (finish(joinHeard(heard.current))) {
        ExpoSpeechRecognitionModule.abort();
      }
    }, STOP_TIMEOUT_MS);
    setStopping(true);
    ExpoSpeechRecognitionModule.stop();
    return done;
  }, [finish]);

  const cancel = useCallback(() => {
    if (finish(null)) ExpoSpeechRecognitionModule.abort();
    heard.current = nothingHeard();
    setTranscript("");
  }, [finish]);

  return { active, stopping, transcript, levels, head, start, stop, cancel };
}
