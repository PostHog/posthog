import { beforeEach, describe, expect, it, vi } from "vitest";
import { createVoiceSession } from "./createVoiceSession";
import { NativeVoiceTransport } from "./nativeVoiceTransport";

const rtc = vi.hoisted(() => {
  const stop = vi.fn();
  const track = { stop };
  const stream = { getTracks: () => [track], release: vi.fn() };
  const channel = { close: vi.fn(), send: vi.fn(), readyState: "open" };
  const peer = {
    close: vi.fn(),
    addTrack: vi.fn(),
    createDataChannel: () => channel,
    createOffer: vi.fn(async () => ({ type: "offer", sdp: "offer" })),
    setLocalDescription: vi.fn(async () => {}),
    setRemoteDescription: vi.fn(async () => {}),
    localDescription: { sdp: "offer" },
    iceGatheringState: "complete",
  };
  return { stop, stream, peer, getUserMedia: vi.fn(async () => stream) };
});
vi.mock("react-native-webrtc", () => ({
  mediaDevices: { getUserMedia: rtc.getUserMedia },
  RTCPeerConnection: class {
    constructor() {
      Object.assign(this, rtc.peer);
    }
  },
}));

describe("NativeVoiceTransport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    rtc.getUserMedia.mockResolvedValue(rtc.stream);
    rtc.peer.iceGatheringState = "complete";
  });

  it("binds the native session without requesting microphone access", () => {
    const session = createVoiceSession({
      createSession: async () => "answer",
      sendMessage: async () => true,
      onState: vi.fn(),
      onEnded: vi.fn(),
    });
    session.stop();
    expect(rtc.getUserMedia).not.toHaveBeenCalled();
  });

  it("releases a microphone granted after cancellation", async () => {
    let grant!: (stream: typeof rtc.stream) => void;
    let requested!: () => void;
    const request = new Promise<void>((resolve) => {
      requested = resolve;
    });
    rtc.getUserMedia.mockImplementation(() => {
      requested();
      return new Promise((resolve) => {
        grant = resolve;
      });
    });
    const transport = new NativeVoiceTransport();
    const offer = transport.createOffer(vi.fn(), vi.fn());
    await request;
    transport.close();
    grant(rtc.stream);
    await expect(offer).rejects.toThrow("canceled");
    expect(rtc.stop).toHaveBeenCalledOnce();
    expect(rtc.stream.release).toHaveBeenCalledOnce();
    expect(rtc.peer.addTrack).not.toHaveBeenCalled();
  });

  it("stops capture before the data connection closes", async () => {
    const transport = new NativeVoiceTransport();
    await transport.createOffer(vi.fn(), vi.fn());
    transport.mute();
    expect(rtc.stop).toHaveBeenCalledOnce();
    expect(rtc.stream.release).toHaveBeenCalledOnce();
    expect(rtc.peer.close).not.toHaveBeenCalled();
    transport.close();
    expect(rtc.peer.close).toHaveBeenCalledOnce();
  });
});
