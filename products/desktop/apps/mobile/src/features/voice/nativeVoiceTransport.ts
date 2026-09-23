import type { LiveVoiceTransport } from "@posthog/platform/speech";
import type { MediaStream, RTCPeerConnection } from "react-native-webrtc";

export class NativeVoiceTransport implements LiveVoiceTransport {
  private peer: RTCPeerConnection | null = null;
  private stream: MediaStream | null = null;
  private channel: ReturnType<RTCPeerConnection["createDataChannel"]> | null =
    null;
  private generation = 0;
  private cancelGathering: (() => void) | undefined;

  async createOffer(
    onMessage: (message: string) => void,
    onDisconnect: () => void,
  ): Promise<string> {
    const generation = ++this.generation;
    // Older native builds can still open conversations when voice is disabled.
    const { mediaDevices, RTCPeerConnection } = await import(
      "react-native-webrtc"
    );
    const checkActive = (): void => {
      if (generation !== this.generation) throw new Error("Voice was canceled");
    };
    checkActive();
    const stream = await mediaDevices.getUserMedia({
      audio: true,
      video: false,
    });
    if (generation !== this.generation) {
      for (const track of stream.getTracks()) track.stop();
      stream.release();
      checkActive();
    }
    this.stream = stream;
    const peer = new RTCPeerConnection({});
    this.peer = peer;
    for (const track of stream.getTracks()) peer.addTrack(track, stream);
    const channel = peer.createDataChannel("oai-events");
    this.channel = channel;
    channel.onmessage = (event: { data: unknown }) => {
      if (generation === this.generation && typeof event.data === "string")
        onMessage(event.data);
    };
    const disconnect = (): void => {
      if (generation === this.generation) onDisconnect();
    };
    channel.onclose = disconnect;
    channel.onerror = disconnect;
    peer.onconnectionstatechange = () => {
      if (
        peer.connectionState === "failed" ||
        peer.connectionState === "disconnected"
      )
        disconnect();
    };
    const offer = await peer.createOffer({});
    checkActive();
    await peer.setLocalDescription(offer);
    checkActive();
    await new Promise<void>((resolve, reject) => {
      if (peer.iceGatheringState === "complete") {
        resolve();
        return;
      }
      const cleanup = (): void => {
        clearTimeout(timer);
        peer.onicegatheringstatechange = null;
        this.cancelGathering = undefined;
      };
      const listener = (): void => {
        if (peer.iceGatheringState === "complete") {
          cleanup();
          resolve();
        }
      };
      const timer = setTimeout(() => {
        cleanup();
        reject(new Error("Voice connection timed out"));
      }, 10_000);
      this.cancelGathering = () => {
        cleanup();
        reject(new Error("Voice was canceled"));
      };
      peer.onicegatheringstatechange = listener;
    });
    checkActive();
    const sdp = peer.localDescription?.sdp;
    if (!sdp) throw new Error("Voice connection has no offer");
    return sdp;
  }

  async acceptAnswer(sdp: string): Promise<void> {
    if (!this.peer) throw new Error("Voice was canceled");
    await this.peer.setRemoteDescription({ type: "answer", sdp });
  }

  send(message: string): void {
    if (this.channel?.readyState === "open") this.channel.send(message);
  }

  mute(): void {
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream?.release();
    this.stream = null;
  }

  close(): void {
    ++this.generation;
    this.cancelGathering?.();
    this.mute();
    this.channel?.close();
    this.peer?.close();
    this.peer = null;
    this.channel = null;
  }
}
