import {
  CANVAS_V2_PRESENCE_STALE_MS,
  type CanvasV2Presence,
  type CanvasV2PresencePoint,
  type CanvasV2Viewport,
} from "@posthog/shared";

/** Another person on the board, as the cursor layer and the faces read them. */
export interface PresencePeer {
  clientId: string;
  userId?: number;
  name: string;
  initials: string;
  color: string;
  cursor: CanvasV2PresencePoint | null;
  viewport: CanvasV2Viewport | null;
  selectedIds: readonly string[];
  lastSeenMs: number;
}

/** Eight hues that stay apart in both themes. */
export const CANVAS_V2_PEER_COLORS: readonly string[] = [
  "#f5581d",
  "#2f80ed",
  "#1d9a6c",
  "#9b51e0",
  "#d92d78",
  "#c08a00",
  "#0e9aa7",
  "#e0562d",
];

/** The same seed always picks the same color, so a person keeps theirs. */
export function peerColor(seed: string): string {
  let hash = 0;
  for (let index = 0; index < seed.length; index++) {
    hash = (hash * 31 + seed.charCodeAt(index)) | 0;
  }
  const slot = Math.abs(hash) % CANVAS_V2_PEER_COLORS.length;
  return CANVAS_V2_PEER_COLORS[slot];
}

export function peerInitials(name: string): string {
  const words = name
    .trim()
    .split(/[\s@._-]+/)
    .filter(Boolean);
  if (words.length === 0) return "?";
  const first = words[0][0] ?? "";
  const second = words.length > 1 ? (words[words.length - 1][0] ?? "") : "";
  return `${first}${second}`.toUpperCase();
}

export interface BoardPresenceOptions {
  /** This board view's own client id, so the local cursor is never drawn. */
  localClientId: string;
  /** The name shown when the server sends no name. */
  unknownName: string;
  onChange: (peers: PresencePeer[]) => void;
  staleMs?: number;
  now?: () => number;
}

/**
 * The other people on one board, keyed by client id. A person with no ping
 * inside the stale window is gone, so a closed window clears itself without a
 * leave message.
 */
export class BoardPresenceTracker {
  private readonly peers = new Map<string, PresencePeer>();
  private readonly localClientId: string;
  private readonly unknownName: string;
  private readonly onChange: (peers: PresencePeer[]) => void;
  private readonly staleMs: number;
  private readonly now: () => number;

  constructor(opts: BoardPresenceOptions) {
    this.localClientId = opts.localClientId;
    this.unknownName = opts.unknownName;
    this.onChange = opts.onChange;
    this.staleMs = opts.staleMs ?? CANVAS_V2_PRESENCE_STALE_MS;
    this.now = opts.now ?? (() => Date.now());
  }

  ingest(presence: CanvasV2Presence): void {
    if (presence.clientId === this.localClientId) return;
    const name = presence.userName?.trim() || this.unknownName;
    const seed =
      presence.userId !== undefined
        ? `user:${presence.userId}`
        : `client:${presence.clientId}`;
    this.peers.set(presence.clientId, {
      clientId: presence.clientId,
      userId: presence.userId,
      name,
      initials: peerInitials(name),
      color: peerColor(seed),
      cursor: presence.cursor,
      viewport: presence.viewport,
      selectedIds: presence.selectedIds,
      lastSeenMs: this.now(),
    });
    this.emit();
  }

  /** Drops everyone who went quiet. Emits only when the list changed. */
  prune(): void {
    const cutoff = this.now() - this.staleMs;
    let dropped = false;
    for (const [clientId, peer] of this.peers) {
      if (peer.lastSeenMs >= cutoff) continue;
      this.peers.delete(clientId);
      dropped = true;
    }
    if (dropped) this.emit();
  }

  clear(): void {
    if (this.peers.size === 0) return;
    this.peers.clear();
    this.emit();
  }

  getPeers(): PresencePeer[] {
    return [...this.peers.values()].sort((a, b) =>
      a.name.localeCompare(b.name),
    );
  }

  private emit(): void {
    this.onChange(this.getPeers());
  }
}
