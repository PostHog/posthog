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

const emptyRing = (): number[] => new Array(RING).fill(-1);

export function useDictation(): Dictation {
  const [active, setActive] = useState(false);
  const [transcript, setTranscript] = useState("");
  const levels = useSharedValue<number[]>(emptyRing());
  const head = useSharedValue(-1);
  const count = useRef(0);

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

  // DEMO: bursts of speech-like levels until the recognizer is wired in.
  useEffect(() => {
    if (!active) return;
    let speaking = true;
    let flipAt = Date.now() + 900;
    const timer = setInterval(() => {
      if (Date.now() > flipAt) {
        speaking = !speaking;
        flipAt =
          Date.now() +
          (speaking ? 600 + Math.random() * 900 : 250 + Math.random() * 400);
      }
      push(speaking ? 0.25 + Math.random() * 0.75 : 0);
    }, SAMPLE_MS);
    return () => clearInterval(timer);
  }, [active, push]);

  const start = useCallback(() => {
    count.current = 0;
    levels.value = emptyRing();
    head.value = -1;
    setTranscript("");
    setActive(true);
  }, [levels, head]);

  const stop = useCallback(() => {
    setActive(false);
    return transcript;
  }, [transcript]);

  const cancel = useCallback(() => {
    setActive(false);
    setTranscript("");
  }, []);

  return { active, transcript, levels, head, start, stop, cancel };
}
