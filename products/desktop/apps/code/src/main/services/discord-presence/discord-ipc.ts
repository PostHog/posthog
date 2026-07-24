import { randomUUID } from "node:crypto";
import net from "node:net";
import path from "node:path";
import { TypedEventEmitter } from "@posthog/shared";
import { logger } from "../../utils/logger";

const log = logger.scope("discord-ipc");

/** Discord local-IPC opcodes (see Discord RPC transport docs). */
const OPCODE = {
  HANDSHAKE: 0,
  FRAME: 1,
  CLOSE: 2,
  PING: 3,
  PONG: 4,
} as const;

/** The Rich Presence activity payload sent in a SET_ACTIVITY frame. */
export interface DiscordActivity {
  details?: string;
  state?: string;
  timestamps?: { start?: number; end?: number };
  assets?: {
    large_image?: string;
    large_text?: string;
    small_image?: string;
    small_text?: string;
  };
  instance?: boolean;
}

/** Event → payload map for {@link TypedEventEmitter}. Both are payload-less. */
interface DiscordIpcClientEvents {
  ready: undefined;
  disconnect: undefined;
}

/**
 * Minimal Discord local-IPC client — just enough of the protocol to perform
 * the handshake and push SET_ACTIVITY frames, modelled the same way VS Code's
 * Discord integrations talk to the desktop client. It connects to the first
 * reachable `discord-ipc-{0..9}` socket and emits `ready` once the client
 * acknowledges the handshake, `disconnect` when the socket drops.
 *
 * It performs no reconnection of its own; the owning service decides when to
 * retry so the policy lives in one place.
 */
export class DiscordIpcClient extends TypedEventEmitter<DiscordIpcClientEvents> {
  private socket: net.Socket | null = null;
  private readBuffer = Buffer.alloc(0);
  private ready = false;

  constructor(private readonly clientId: string) {
    super();
  }

  isReady(): boolean {
    return this.ready;
  }

  /** Attempt to connect, trying each candidate socket path in turn. */
  connect(): void {
    if (this.socket) return;
    this.tryConnect(this.candidatePaths(), 0);
  }

  /** Tear down without emitting — used when the owner intentionally stops. */
  destroy(): void {
    if (this.socket) {
      try {
        this.socket.destroy();
      } catch {
        // best effort
      }
      this.socket = null;
    }
    this.ready = false;
    this.readBuffer = Buffer.alloc(0);
    this.removeAllListeners();
  }

  setActivity(activity: DiscordActivity | null): void {
    if (!this.socket || !this.ready) return;
    this.write(OPCODE.FRAME, {
      cmd: "SET_ACTIVITY",
      args: { pid: process.pid, activity: activity ?? undefined },
      nonce: randomUUID(),
    });
  }

  private tryConnect(paths: string[], index: number): void {
    if (index >= paths.length) {
      this.emit("disconnect", undefined);
      return;
    }

    const sock = net.createConnection(paths[index]);

    const onError = () => {
      sock.removeAllListeners();
      sock.destroy();
      this.tryConnect(paths, index + 1);
    };

    sock.once("error", onError);
    sock.once("connect", () => {
      sock.removeListener("error", onError);
      this.socket = sock;
      sock.on("data", (chunk) => this.onData(chunk));
      sock.on("error", () => {
        // Surfaced via the subsequent "close" event.
      });
      sock.on("close", () => this.handleClose());
      this.write(OPCODE.HANDSHAKE, { v: 1, client_id: this.clientId });
    });
  }

  private candidatePaths(): string[] {
    const ids = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];

    if (process.platform === "win32") {
      return ids.map((id) => `\\\\?\\pipe\\discord-ipc-${id}`);
    }

    const base =
      process.env.XDG_RUNTIME_DIR ||
      process.env.TMPDIR ||
      process.env.TMP ||
      process.env.TEMP ||
      "/tmp";
    const root = base.replace(/\/$/, "");
    // Discord may live at the temp root or under a sandbox subdir (Snap/Flatpak).
    const dirs = [
      root,
      path.join(root, "snap.discord"),
      path.join(root, "app", "com.discordapp.Discord"),
      path.join(root, "app", "com.discordapp.DiscordCanary"),
    ];
    return dirs.flatMap((dir) =>
      ids.map((id) => path.join(dir, `discord-ipc-${id}`)),
    );
  }

  private onData(chunk: Buffer): void {
    this.readBuffer = Buffer.concat([this.readBuffer, chunk]);
    // Frames are [Int32LE opcode][Int32LE length][JSON body].
    while (this.readBuffer.length >= 8) {
      const op = this.readBuffer.readInt32LE(0);
      const len = this.readBuffer.readInt32LE(4);
      if (this.readBuffer.length < 8 + len) break;
      const body = this.readBuffer.subarray(8, 8 + len);
      this.readBuffer = this.readBuffer.subarray(8 + len);
      this.handleFrame(op, body);
    }
  }

  private handleFrame(op: number, body: Buffer): void {
    if (op === OPCODE.PING) {
      this.write(OPCODE.PONG, this.parse(body));
      return;
    }
    if (op === OPCODE.CLOSE) {
      this.handleClose();
      return;
    }
    if (op === OPCODE.FRAME) {
      const msg = this.parse(body) as { cmd?: string; evt?: string } | null;
      if (msg?.cmd === "DISPATCH" && msg.evt === "READY") {
        this.ready = true;
        log.info("Discord IPC handshake complete");
        this.emit("ready", undefined);
      }
    }
  }

  private handleClose(): void {
    if (!this.socket) return;
    this.ready = false;
    this.readBuffer = Buffer.alloc(0);
    try {
      this.socket.destroy();
    } catch {
      // best effort
    }
    this.socket = null;
    this.emit("disconnect", undefined);
  }

  private write(op: number, payload: unknown): void {
    if (!this.socket) return;
    const json = Buffer.from(JSON.stringify(payload), "utf8");
    const header = Buffer.alloc(8);
    header.writeInt32LE(op, 0);
    header.writeInt32LE(json.length, 4);
    this.socket.write(Buffer.concat([header, json]));
  }

  private parse(body: Buffer): unknown {
    try {
      return JSON.parse(body.toString("utf8"));
    } catch {
      return null;
    }
  }
}
