import { type AvatarColor, avatarColor } from "@posthog/core/auth/avatarColor";
import {
  getUserInitials,
  type UserLike,
} from "@posthog/core/auth/userInitials";
import {
  CANVAS_V2_PRESENCE_STALE_MS,
  type CanvasV2Presence,
  type CanvasV2PresenceCaret,
  type CanvasV2PresencePoint,
  type CanvasV2Viewport,
} from "@posthog/shared";

/** Another person on the board, as the cursor layer and the faces read them. */
export interface AvatarPerson extends UserLike {
  uuid?: string | null;
}

export interface PresencePeer {
  clientId: string;
  userId?: number;
  user: AvatarPerson;
  name: string;
  initials: string;
  color: AvatarColor;
  cursor: CanvasV2PresencePoint | null;
  viewport: CanvasV2Viewport | null;
  selectedIds: readonly string[];
  /** Where this person edits a mergeable field, as entry ids. */
  carets: readonly CanvasV2PresenceCaret[];
  lastSeenMs: number;
}

/** Eight hues that stay apart in both themes. */

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
      presence.userUuid ??
      (presence.userId !== undefined
        ? `user:${presence.userId}`
        : `client:${presence.clientId}`);
    const [firstName, ...restName] = name.split(/\s+/).filter(Boolean);
    const user: AvatarPerson = {
      uuid: presence.userUuid ?? null,
      first_name: firstName ?? null,
      last_name: restName.join(" ") || null,
      email: presence.userEmail ?? null,
    };
    this.peers.set(presence.clientId, {
      clientId: presence.clientId,
      userId: presence.userId,
      user,
      name,
      initials: getUserInitials(user),
      color: avatarColor(seed),
      cursor: presence.cursor,
      viewport: presence.viewport,
      selectedIds: presence.selectedIds,
      carets: presence.carets,
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
