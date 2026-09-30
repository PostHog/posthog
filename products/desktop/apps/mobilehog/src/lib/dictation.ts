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
  active: boolean;
  transcript: string;
  // Read on the UI thread by the waveform; updating them never re-renders React.
  levels: SharedValue<number[]>;
  head: SharedValue<number>;
  start: () => void;
  // Ends dictation and keeps what was heard.
  stop: () => string;
  cancel: () => void;
}

export interface Heard {
  finals: string[];
  interim: string;
}

// The recognizer reports volume from -2 to 10; below QUIET is room noise.
const QUIET = 1;
const LOUD = 8;

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

// Only a plain language-region tag; anything else falls back to the recognizer default.
export function recognitionLang(locale: string): string | undefined {
  return /^([a-z]{2,3}-[A-Z]{2})(?:-u-|$)/.exec(locale)?.[1];
}

const emptyRing = (): number[] => new Array(RING).fill(-1);
const nothingHeard = (): Heard => ({ finals: [], interim: "" });

// onEnd receives what was heard when the recognizer ends on its own.
export function useDictation(onEnd?: (heard: string) => void): Dictation {
  const [active, setActive] = useState(false);
  const [transcript, setTranscript] = useState("");
  const levels = useSharedValue<number[]>(emptyRing());
  const head = useSharedValue(-1);
  const count = useRef(0);
  const heard = useRef<Heard>(nothingHeard());
  // Bumped on every start and finish so a late permission answer cannot restart a finished session.
  const session = useRef(0);
  const live = useRef(false);
  const listening = useRef(false);
  const endRef = useRef(onEnd);
  endRef.current = onEnd;

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

  const finish = useCallback((): boolean => {
    const wasListening = listening.current;
    session.current++;
    live.current = false;
    listening.current = false;
    setActive(false);
    return wasListening;
  }, []);

  // Before native start, an end or error can only come from the previous session.
  const endQuietly = useCallback(() => {
    if (!live.current || !listening.current) return;
    finish();
    endRef.current?.(joinHeard(heard.current));
  }, [finish]);

  useSpeechRecognitionEvent("volumechange", (event) => {
    if (live.current) push(volumeToLevel(event.value));
  });

  useSpeechRecognitionEvent("result", (event) => {
    if (!live.current) return;
    heard.current = applyResult(heard.current, event);
    setTranscript(joinHeard(heard.current));
  });

  useSpeechRecognitionEvent("error", (event) => {
    if (event.error !== "aborted") endQuietly();
  });

  useSpeechRecognitionEvent("end", endQuietly);

  useEffect(
    () => () => {
      session.current++;
      live.current = false;
      if (listening.current) ExpoSpeechRecognitionModule.abort();
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

  const stop = useCallback((): string => {
    const text = joinHeard(heard.current);
    if (finish()) ExpoSpeechRecognitionModule.stop();
    return text;
  }, [finish]);

  const cancel = useCallback(() => {
    if (finish()) ExpoSpeechRecognitionModule.abort();
    heard.current = nothingHeard();
    setTranscript("");
  }, [finish]);

  return { active, transcript, levels, head, start, stop, cancel };
}
