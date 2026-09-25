import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

type SpeechModule =
  typeof import("expo-speech-recognition")["ExpoSpeechRecognitionModule"];
type Status = "idle" | "starting" | "recording" | "stopping";

function abortRecognition(module: SpeechModule | null): void {
  try {
    module?.abort();
  } catch {}
}

export function useDictation(onTranscript: (text: string) => void) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState("");
  const callback = useRef(onTranscript);
  callback.current = onTranscript;
  const active = useRef(false);
  const recordingId = useRef(0);
  const mounted = useRef(true);
  const speech = useRef<SpeechModule | null>(null);
  const transcript = useRef("");
  const removers = useRef<(() => void)[]>([]);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const finish = useCallback((keep: boolean) => {
    const text = active.current && keep ? transcript.current.trim() : "";
    active.current = false;
    recordingId.current += 1;
    transcript.current = "";
    for (const remove of removers.current) remove();
    removers.current = [];
    if (timeout.current) clearTimeout(timeout.current);
    timeout.current = null;
    if (mounted.current) {
      setStatus("idle");
      setPreview("");
      if (text) callback.current(text);
    }
  }, []);

  const cancel = useCallback(() => {
    if (!active.current) return;
    finish(false);
    abortRecognition(speech.current);
  }, [finish]);

  useFocusEffect(useCallback(() => () => cancel(), [cancel]));

  const start = async (): Promise<void> => {
    if (active.current) return;
    active.current = true;
    const id = ++recordingId.current;
    setStatus("starting");
    setError(null);
    try {
      const { ExpoSpeechRecognitionModule: module } = await import(
        "expo-speech-recognition"
      );
      if (!mounted.current || !active.current || id !== recordingId.current)
        return;
      speech.current = module;
      if (!module.isRecognitionAvailable())
        throw new Error(
          "Voice input is not available on this device. Use the keyboard.",
        );
      const permission = await module.requestPermissionsAsync();
      if (!mounted.current || !active.current || id !== recordingId.current)
        return;
      if (!permission.granted)
        throw new Error(
          "Allow microphone and speech recognition access in iOS Settings, then try again.",
        );
      const result = module.addListener("result", (event) => {
        const text = event.results[0]?.transcript;
        if (text) {
          transcript.current = text;
          setPreview(text);
        }
        if (event.isFinal) {
          finish(true);
          abortRecognition(module);
        }
      });
      const end = module.addListener("end", () => finish(true));
      const failure = module.addListener("error", (event) => {
        if (event.error !== "aborted")
          setError(
            event.error === "no-speech"
              ? "No speech detected. Tap the microphone to try again."
              : "Voice input stopped. Check your connection and try again.",
          );
        finish(true);
      });
      removers.current = [
        () => result.remove(),
        () => end.remove(),
        () => failure.remove(),
      ];
      module.start({
        lang: "en-US",
        interimResults: true,
        requiresOnDeviceRecognition: module.supportsOnDeviceRecognition(),
        addsPunctuation: true,
      });
      setStatus("recording");
    } catch (cause) {
      if (mounted.current)
        setError(
          cause instanceof Error
            ? cause.message
            : "Voice input failed. Install the latest native build and try again.",
        );
      finish(true);
    }
  };

  const stop = (): void => {
    if (!active.current || !speech.current) return;
    setStatus("stopping");
    timeout.current = setTimeout(() => {
      finish(true);
      abortRecognition(speech.current);
    }, 2000);
    try {
      speech.current.stop();
    } catch {
      finish(true);
    }
  };

  useEffect(() => {
    mounted.current = true;
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "background" && active.current) {
        finish(true);
        abortRecognition(speech.current);
      }
    });
    return () => {
      mounted.current = false;
      cancel();
      subscription.remove();
    };
  }, [cancel, finish]);

  return { status, error, preview, start, stop, cancel };
}
