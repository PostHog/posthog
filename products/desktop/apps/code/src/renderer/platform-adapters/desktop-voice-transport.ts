import type {
  LiveVoiceTransport,
  VoiceAudioLevels,
} from "@posthog/platform/speech";

export class DesktopVoiceTransport implements LiveVoiceTransport {
  private peer: RTCPeerConnection | null = null;
  private stream: MediaStream | null = null;
  private channel: RTCDataChannel | null = null;
  private audio: HTMLAudioElement | null = null;
  private generation = 0;
  private audioMeterTimeout: ReturnType<typeof setTimeout> | undefined;
  private cancelGathering: (() => void) | undefined;

  private async measureAudio(
    peer: RTCPeerConnection,
    generation: number,
    onAudioLevels: (levels: VoiceAudioLevels) => void,
  ): Promise<void> {
    if (generation !== this.generation || !this.stream) return;
    const levels: VoiceAudioLevels = { input: 0, output: 0 };
    try {
      const stats = await peer.getStats();
      for (const report of stats.values()) {
        if (
          report.kind !== "audio" ||
          typeof report.audioLevel !== "number" ||
          !Number.isFinite(report.audioLevel)
        )
          continue;
        const level = Math.min(1, Math.max(0, report.audioLevel));
        if (report.type === "media-source")
          levels.input = Math.max(levels.input, level);
        if (report.type === "inbound-rtp")
          levels.output = Math.max(levels.output, level);
      }
    } catch {
      // Level metering must not interrupt a voice connection.
    }
    // boffin: A late stats result must not restart metering after the microphone stops.
    if (generation !== this.generation || !this.stream) return;
    onAudioLevels(levels);
    this.audioMeterTimeout = setTimeout(
      () => void this.measureAudio(peer, generation, onAudioLevels),
      100,
    );
  }

  async createOffer(
    onMessage: (message: string) => void,
    onDisconnect: () => void,
    onAudioLevels?: (levels: VoiceAudioLevels) => void,
  ): Promise<string> {
    const generation = ++this.generation;
    const checkActive = (): void => {
      if (generation !== this.generation) throw new Error("Voice was canceled");
    };
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
      video: false,
    });
    if (generation !== this.generation) {
      for (const track of stream.getTracks()) track.stop();
      checkActive();
    }
    this.stream = stream;
    const peer = new RTCPeerConnection();
    this.peer = peer;
    const audio = new Audio();
    audio.autoplay = true;
    this.audio = audio;
    const disconnect = (): void => {
      if (generation === this.generation) onDisconnect();
    };
    peer.ontrack = (event) => {
      if (generation !== this.generation) return;
      audio.srcObject = event.streams[0] ?? new MediaStream([event.track]);
      void audio.play().catch(disconnect);
    };
    for (const track of stream.getTracks()) {
      track.onended = disconnect;
      peer.addTrack(track, stream);
    }
    const channel = peer.createDataChannel("oai-events");
    this.channel = channel;
    channel.onmessage = (event: MessageEvent<unknown>) => {
      if (generation === this.generation && typeof event.data === "string")
        onMessage(event.data);
    };
    channel.onclose = disconnect;
    channel.onerror = disconnect;
    peer.onconnectionstatechange = () => {
      if (peer.connectionState === "failed") disconnect();
    };
    const offer = await peer.createOffer();
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
      const timer = setTimeout(() => {
        cleanup();
        reject(new Error("Voice connection timed out"));
      }, 10_000);
      this.cancelGathering = () => {
        cleanup();
        reject(new Error("Voice was canceled"));
      };
      peer.onicegatheringstatechange = () => {
        if (peer.iceGatheringState === "complete") {
          cleanup();
          resolve();
        }
      };
    });
    checkActive();
    if (onAudioLevels) void this.measureAudio(peer, generation, onAudioLevels);
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
    clearTimeout(this.audioMeterTimeout);
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    this.audio?.pause();
  }

  close(): void {
    ++this.generation;
    this.cancelGathering?.();
    this.mute();
    if (this.audio) this.audio.srcObject = null;
    this.channel?.close();
    this.peer?.close();
    this.audio = null;
    this.peer = null;
    this.channel = null;
  }
}
