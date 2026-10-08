import "reflect-metadata";
import type { ISecureStoreService } from "@posthog/workspace-server/services/secure-store/identifiers";
import { describe, expect, it, vi } from "vitest";

vi.mock("@main/utils/logger", () => ({
  logger: { scope: () => ({ info: vi.fn(), warn: vi.fn() }) },
}));

import { ElevenLabsSpeechService } from "./service";

describe("ElevenLabsSpeechService", () => {
  it("keeps the voice id inside one path segment", async () => {
    const fetchMock = vi.fn(
      async (_url: string) => new Response(new ArrayBuffer(8), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const secureStore = {
      getItem: () => "test-key",
    } as unknown as ISecureStoreService;

    await new ElevenLabsSpeechService(secureStore).synthesize(
      "hello",
      "../convai/knowledge-base/text",
    );

    const url = new URL(fetchMock.mock.calls[0][0]);
    expect(url.origin).toBe("https://api.elevenlabs.io");
    expect(url.pathname).toBe(
      "/v1/text-to-speech/..%2Fconvai%2Fknowledge-base%2Ftext",
    );
  });
});
