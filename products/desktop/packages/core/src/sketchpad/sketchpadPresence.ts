import { type AvatarColor, avatarColor } from "@posthog/core/auth/avatarColor";
import {
  getUserInitials,
  type UserLike,
} from "@posthog/core/auth/userInitials";
import {
  SKETCHPAD_PRESENCE_STALE_MS,
  type SketchpadPresence,
  type SketchpadPresenceCaret,
  type SketchpadPresencePoint,
  type SketchpadViewport,
} from "@posthog/shared";

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
  cursor: SketchpadPresencePoint | null;
  viewport: SketchpadViewport | null;
  selectedIds: readonly string[];
  carets: readonly SketchpadPresenceCaret[];
  lastSeenMs: number;
}

export interface SketchpadPresenceOptions {
  localClientId: string;
  unknownName: string;
  onChange: (peers: PresencePeer[]) => void;
  staleMs?: number;
  now?: () => number;
}

export class SketchpadPresenceTracker {
  private readonly peers = new Map<string, PresencePeer>();
  private readonly localClientId: string;
  private readonly unknownName: string;
  private readonly onChange: (peers: PresencePeer[]) => void;
  private readonly staleMs: number;
  private readonly now: () => number;

  constructor(opts: SketchpadPresenceOptions) {
    this.localClientId = opts.localClientId;
    this.unknownName = opts.unknownName;
    this.onChange = opts.onChange;
    this.staleMs = opts.staleMs ?? SKETCHPAD_PRESENCE_STALE_MS;
    this.now = opts.now ?? (() => Date.now());
  }

  ingest(presence: SketchpadPresence): void {
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
