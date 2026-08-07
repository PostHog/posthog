import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  addCustomSound,
  setCompletionSound,
  decodeAudioClip,
  blobToDataUrl,
  track,
} = vi.hoisted(() => ({
  addCustomSound: vi.fn(),
  setCompletionSound: vi.fn(),
  decodeAudioClip: vi.fn(),
  blobToDataUrl: vi.fn(),
  track: vi.fn(),
}));

// Mock only the Web Audio seam; the pure trim logic (detectSilenceBounds,
// shouldOfferTrim, resolveSaveClip, encodeWavDataUrl) stays real so this test
// exercises the real wiring end to end.
vi.mock("@posthog/ui/utils/customSound", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@posthog/ui/utils/customSound")>();
  return { ...actual, decodeAudioClip, blobToDataUrl };
});

vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: (selector: (s: unknown) => unknown) =>
    selector({ addCustomSound, setCompletionSound }),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));

import { AddCustomSoundDialog } from "./AddCustomSoundDialog";

// Fake decoded clip: 0.4s silence + 0.6s tone + 0.4s silence at 1kHz (1.4s).
function fakeBuffer(): AudioBuffer {
  const samples = [
    ...new Array(400).fill(0),
    ...new Array(600).fill(0.8),
    ...new Array(400).fill(0),
  ];
  const data = Float32Array.from(samples);
  return {
    sampleRate: 1000,
    length: data.length,
    duration: data.length / 1000,
    numberOfChannels: 1,
    getChannelData: () => data,
  } as unknown as AudioBuffer;
}

describe("AddCustomSoundDialog", () => {
  beforeEach(() => {
    addCustomSound.mockReset();
    setCompletionSound.mockReset();
    decodeAudioClip.mockReset().mockResolvedValue(fakeBuffer());
    blobToDataUrl.mockReset().mockResolvedValue("data:audio/wav;base64,AAAA");
    track.mockReset();
  });

  it("imports a clip, offers + applies silence trim, and saves the trimmed result", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <AddCustomSoundDialog open onOpenChange={vi.fn()} />
      </Theme>,
    );

    const file = new File([new Uint8Array([1, 2, 3])], "ding.wav", {
      type: "audio/wav",
    });
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await user.upload(input, file);

    // Decoded to 1.4s, and a trim is offered because of the leading/trailing
    // silence.
    expect(await screen.findByText(/Clip ready · 1\.4s/)).toBeInTheDocument();
    const trimButton = screen.getByRole("button", { name: /Trim silence/ });

    await user.click(trimButton);

    // 0.6s tone + 0.05s padding each side = 0.7s.
    expect(await screen.findByText(/Trimmed · 0\.7s/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Keep full clip/ }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(addCustomSound).toHaveBeenCalledTimes(1);
    const saved = addCustomSound.mock.calls[0][0];
    // Name seeded from the filename.
    expect(saved.name).toBe("ding");
    // Trimmed -> re-encoded to WAV with the shortened duration: the 600ms tone
    // (samples 400–999) plus 50ms padding each side at 1kHz.
    expect(saved.dataUrl.startsWith("data:audio/wav;base64,")).toBe(true);
    expect(saved.durationMs).toBe(700);
    // The new sound is selected as the active completion sound.
    expect(setCompletionSound).toHaveBeenCalledWith(`custom:${saved.id}`);
    // Usage event fires with the capture source, trim state, and duration.
    expect(track).toHaveBeenCalledWith("Custom sound added", {
      source: "import",
      trimmed: true,
      duration_ms: 700,
    });
  });
});
