import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DesktopVoiceTransport } from "./desktop-voice-transport";

describe("DesktopVoiceTransport", () => {
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop }] };
  const getUserMedia = vi.fn(async () => stream);
  let audio: HTMLAudioElement;
  let peer: RTCPeerConnection;

  beforeEach(() => {
    vi.clearAllMocks();
    getUserMedia.mockResolvedValue(stream);
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
    vi.stubGlobal(
      "Audio",
      class {
        autoplay = false;
        srcObject = null;
        play = vi.fn(async () => {});
        pause = vi.fn();
        constructor() {
          audio = this as unknown as HTMLAudioElement;
        }
      },
    );
    vi.stubGlobal(
      "RTCPeerConnection",
      class {
        localDescription = { sdp: "offer" };
        iceGatheringState = "complete";
        addTrack = vi.fn();
        createOffer = vi.fn(async () => ({ type: "offer", sdp: "offer" }));
        setLocalDescription = vi.fn(async () => {});
        setRemoteDescription = vi.fn(async () => {});
        createDataChannel = () => ({
          close: vi.fn(),
          send: vi.fn(),
          readyState: "open",
        });
        close = vi.fn();
        constructor() {
          peer = this as unknown as RTCPeerConnection;
        }
      },
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("releases a microphone granted after cancellation", async () => {
    let grant!: (value: typeof stream) => void;
    getUserMedia.mockImplementation(
      () =>
        new Promise((resolve) => {
          grant = resolve;
        }),
    );
    const transport = new DesktopVoiceTransport();
    const offer = transport.createOffer(vi.fn(), vi.fn());
    transport.close();
    grant(stream);
    await expect(offer).rejects.toThrow("canceled");
    expect(stop).toHaveBeenCalledOnce();
  });

  it("plays remote audio and stops capture before closing the data connection", async () => {
    const transport = new DesktopVoiceTransport();
    await transport.createOffer(vi.fn(), vi.fn());
    peer.ontrack?.call(peer, { streams: [stream] } as unknown as RTCTrackEvent);
    expect(audio.srcObject).toBe(stream);
    expect(audio.play).toHaveBeenCalledOnce();
    transport.mute();
    expect(stop).toHaveBeenCalledOnce();
    expect(audio.pause).toHaveBeenCalledOnce();
    expect(peer.close).not.toHaveBeenCalled();
    transport.close();
    expect(audio.srcObject).toBeNull();
    expect(peer.close).toHaveBeenCalledOnce();
  });
});
