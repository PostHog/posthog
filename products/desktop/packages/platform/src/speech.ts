export interface SpeakOptions {
  /** ElevenLabs voice id to synthesize with. Adapter picks a default when omitted. */
  voiceId?: string;
}

/**
 * Host capability for speaking a line out loud (text-to-speech). Best-effort:
 * `speak` must never throw and should resolve when playback finishes (or is
 * skipped), so a caller can serialize utterances one at a time. The Electron
 * adapter synthesizes expressive audio via ElevenLabs when a key is configured
 * and falls back to the system voice otherwise.
 */
export interface ISpeech {
  /** True when any playback path is available (system voice or configured key). */
  isSupported(): boolean;
  /** Speak `text`; resolves when playback ends. Never rejects. */
  speak(text: string, opts?: SpeakOptions): Promise<void>;
  /** Stop any in-progress playback immediately. */
  stop(): void;
}

export const SPEECH_SERVICE = Symbol.for("posthog.platform.speech");
