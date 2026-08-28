import { logger } from "@main/utils/logger";
import {
  type ISecureStoreService,
  SECURE_STORE_SERVICE,
} from "@posthog/workspace-server/services/secure-store/identifiers";
import {
  ELEVENLABS_API_KEY_STORE_KEY,
  type ISpeechSynthesizer,
  type SpeechSynthesisResult,
} from "@posthog/workspace-server/services/speech/identifiers";
import { inject, injectable } from "inversify";

const log = logger.scope("speech");

// Expressive default voice (Eleven v3). Overridable per call via voiceId.
const DEFAULT_VOICE_ID = "goT3UYdM9bhm0n2lmKQx";
const MODEL_ID = "eleven_v3";
const OUTPUT_FORMAT = "mp3_44100_128";
// Cache synthesized audio by voice+text so repeated lines (e.g. the "finished"
// backstop for a given task) aren't re-billed/re-fetched. Bounded LRU — audio
// is ~100KB, so this caps at a few MB.
const CACHE_MAX = 32;

/**
 * ElevenLabs-backed speech synthesizer. Reads the API key from encrypted secure
 * storage and returns MP3 bytes to the renderer, which plays them (host-neutral
 * playback). When no key is configured or synthesis fails, returns null so the
 * renderer falls back to the system voice. Best-effort — never throws.
 */
@injectable()
export class ElevenLabsSpeechService implements ISpeechSynthesizer {
  // voice+text -> audioBase64; insertion-ordered for LRU eviction.
  private readonly cache = new Map<string, string>();

  constructor(
    @inject(SECURE_STORE_SERVICE)
    private readonly secureStore: ISecureStoreService,
  ) {}

  async synthesize(
    text: string,
    voiceId?: string,
  ): Promise<SpeechSynthesisResult | null> {
    const apiKey = this.secureStore.getItem(ELEVENLABS_API_KEY_STORE_KEY);
    if (!apiKey) {
      log.info("No ElevenLabs key configured — using system voice");
      return null;
    }
    const voice = voiceId?.trim() || DEFAULT_VOICE_ID;

    const cacheKey = `${voice}:${text}`;
    const cached = this.cache.get(cacheKey);
    if (cached !== undefined) {
      // Refresh recency (delete + re-set moves it to the end).
      this.cache.delete(cacheKey);
      this.cache.set(cacheKey, cached);
      log.info(`Speech cache hit (voice=${voice}, chars=${text.length})`);
      return { audioBase64: cached, mimeType: "audio/mpeg" };
    }

    log.info(
      `Synthesizing via ElevenLabs (voice=${voice}, chars=${text.length})`,
    );
    try {
      const res = await fetch(
        `https://api.elevenlabs.io/v1/text-to-speech/${voice}?output_format=${OUTPUT_FORMAT}`,
        {
          method: "POST",
          headers: { "xi-api-key": apiKey, "content-type": "application/json" },
          body: JSON.stringify({
            text,
            model_id: MODEL_ID,
            voice_settings: { stability: 0.5 },
          }),
        },
      );
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        log.warn(
          `ElevenLabs failed: HTTP ${res.status} ${detail.slice(0, 300)}`,
        );
        return null;
      }
      const buffer = Buffer.from(await res.arrayBuffer());
      const audioBase64 = buffer.toString("base64");
      this.cache.set(cacheKey, audioBase64);
      if (this.cache.size > CACHE_MAX) {
        this.cache.delete(this.cache.keys().next().value as string);
      }
      return { audioBase64, mimeType: "audio/mpeg" };
    } catch (error) {
      log.warn("ElevenLabs synthesis error", error);
      return null;
    }
  }
}
