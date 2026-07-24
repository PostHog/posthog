import { ExpoSpeechRecognitionModule } from "expo-speech-recognition";
import { useCallback, useEffect, useRef, useState } from "react";
import { logger } from "@/lib/logger";

const log = logger.scope("voice-recording");

type RecordingStatus = "idle" | "recording" | "transcribing" | "error";

interface UseVoiceRecordingOptions {
  /**
   * Fires with the final transcript whenever recognition finishes — whether
   * the caller invoked stopRecording() or the engine ended on its own
   * (silence timeout on iOS 17-, `isFinal` result on iOS 18+/Android, etc).
   * Use this to append voice input to a text field reliably; the previous
   * promise-only API silently dropped transcripts when the engine auto-ended
   * before the user tapped stop.
   */
  onTranscript?: (transcript: string) => void;
}

interface UseVoiceRecordingReturn {
  status: RecordingStatus;
  error: string | null;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<void>;
  cancelRecording: () => Promise<void>;
}

export function useVoiceRecording(
  options: UseVoiceRecordingOptions = {},
): UseVoiceRecordingReturn {
  const [status, setStatus] = useState<RecordingStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const transcriptRef = useRef<string>("");
  const listenersRef = useRef<(() => void)[]>([]);
  /** Resolves stopRecording() when a final event arrives. Null otherwise. */
  const stopWaitRef = useRef<(() => void) | null>(null);
  /** Set by cancelRecording so the next event discards the transcript. */
  const canceledRef = useRef(false);
  /** Keep the latest callback without re-attaching listeners. */
  const onTranscriptRef = useRef(options.onTranscript);
  useEffect(() => {
    onTranscriptRef.current = options.onTranscript;
  });

  const removeListeners = useCallback(() => {
    for (const remove of listenersRef.current) {
      try {
        remove();
      } catch {}
    }
    listenersRef.current = [];
  }, []);

  /**
   * Called when the engine emits a terminal event: a `result` with
   * `isFinal: true`, an `end` event, or a non-fatal error like `no-speech`.
   * Delivers the transcript via the callback and tears down listeners.
   *
   * This must work even when the user hasn't called stopRecording() — on
   * iOS 17- the engine ends after ~3s of silence regardless, and on iOS 18+
   * a short utterance can finalize before the user taps stop.
   */
  const handleFinalEvent = useCallback(() => {
    const wasCanceled = canceledRef.current;
    canceledRef.current = false;
    const text = wasCanceled ? "" : transcriptRef.current.trim();
    log.debug("final event", { text: text.slice(0, 60), wasCanceled });

    removeListeners();
    transcriptRef.current = "";
    setStatus("idle");

    if (text) {
      onTranscriptRef.current?.(text);
    }

    const waiter = stopWaitRef.current;
    stopWaitRef.current = null;
    if (waiter) waiter();
  }, [removeListeners]);

  const startRecording = useCallback(async () => {
    try {
      // Tear down any lingering state from a prior session so we don't pick
      // up stale listeners or transcripts.
      removeListeners();
      stopWaitRef.current = null;
      canceledRef.current = false;
      transcriptRef.current = "";
      setError(null);

      if (!ExpoSpeechRecognitionModule.isRecognitionAvailable()) {
        setError("Speech recognition is not available on this device");
        setStatus("error");
        return;
      }

      const { granted } =
        await ExpoSpeechRecognitionModule.requestPermissionsAsync();
      if (!granted) {
        setError("Speech recognition permission is required");
        setStatus("error");
        return;
      }

      const resultSub = ExpoSpeechRecognitionModule.addListener(
        "result",
        (event) => {
          const best = event.results[0]?.transcript;
          if (best) transcriptRef.current = best;
          log.debug("result", { isFinal: event.isFinal, hasText: !!best });
          if (event.isFinal) {
            handleFinalEvent();
          }
        },
      );

      const errorSub = ExpoSpeechRecognitionModule.addListener(
        "error",
        (event) => {
          log.debug("error event", {
            code: event.error,
            message: event.message,
          });
          // "no-speech" and "aborted" are non-fatal — fall through the
          // normal end path so any accumulated transcript still delivers.
          if (event.error === "no-speech" || event.error === "aborted") {
            handleFinalEvent();
            return;
          }
          setError(event.message || "Speech recognition failed");
          removeListeners();
          transcriptRef.current = "";
          const waiter = stopWaitRef.current;
          stopWaitRef.current = null;
          setStatus("error");
          waiter?.();
        },
      );

      const endSub = ExpoSpeechRecognitionModule.addListener("end", () => {
        log.debug("end event", { hasTranscript: !!transcriptRef.current });
        handleFinalEvent();
      });

      listenersRef.current = [
        () => resultSub.remove(),
        () => errorSub.remove(),
        () => endSub.remove(),
      ];

      const useOnDevice =
        ExpoSpeechRecognitionModule.supportsOnDeviceRecognition();

      ExpoSpeechRecognitionModule.start({
        lang: "en-US",
        interimResults: true,
        requiresOnDeviceRecognition: useOnDevice,
        addsPunctuation: true,
      });

      setStatus("recording");
    } catch (err) {
      log.error("Failed to start speech recognition", err);
      setError("Failed to start speech recognition");
      setStatus("error");
    }
  }, [removeListeners, handleFinalEvent]);

  const stopRecording = useCallback(async (): Promise<void> => {
    // Engine already auto-finished — transcript was delivered via callback.
    if (status !== "recording") return;

    setStatus("transcribing");

    try {
      ExpoSpeechRecognitionModule.stop();
    } catch (err) {
      log.warn("Speech recognition stop failed", err);
    }

    // Wait briefly for the platform's final event so the transcript is fully
    // formed. Some Android engines never fire result/end after a manual stop;
    // the timeout flushes whatever interim results we captured so the caller
    // doesn't hang on "Transcribing…" forever.
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      const timeoutId = setTimeout(() => {
        log.warn("stop timeout — flushing interim transcript");
        const text = transcriptRef.current.trim();
        removeListeners();
        transcriptRef.current = "";
        stopWaitRef.current = null;
        setStatus("idle");
        if (text) onTranscriptRef.current?.(text);
        finish();
      }, 1500);
      stopWaitRef.current = () => {
        clearTimeout(timeoutId);
        finish();
      };
    });
  }, [status, removeListeners]);

  const cancelRecording = useCallback(async () => {
    canceledRef.current = true;
    try {
      ExpoSpeechRecognitionModule.abort();
    } catch {}
    removeListeners();
    transcriptRef.current = "";
    const waiter = stopWaitRef.current;
    stopWaitRef.current = null;
    setStatus("idle");
    setError(null);
    waiter?.();
  }, [removeListeners]);

  // Tear down any in-flight recognition on unmount so events don't dispatch
  // into a torn-down component.
  useEffect(() => {
    return () => {
      try {
        ExpoSpeechRecognitionModule.abort();
      } catch {}
      removeListeners();
    };
  }, [removeListeners]);

  return {
    status,
    error,
    startRecording,
    stopRecording,
    cancelRecording,
  };
}
