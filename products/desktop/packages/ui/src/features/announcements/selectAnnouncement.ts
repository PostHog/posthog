import { isVersionNewer } from "@posthog/core/updates/version";
import {
  type Announcement,
  announcementSchema,
  announcementsEnvelopeSchema,
} from "@posthog/shared/announcements";

export interface ActiveAnnouncement {
  announcement: Announcement;
  /** The app is below the announcement's minVersion — show an update action. */
  needsUpdate: boolean;
}

export interface SelectAnnouncementInput {
  /** Raw flag payload, exactly as PostHog returned it. */
  payload: unknown;
  now: number;
  /** null = version unknown (web host, query unresolved) — nothing is shown. */
  appVersion: string | null;
  isDevBuild: boolean;
  dismissedIds: ReadonlySet<string>;
  /**
   * An announcement was already dismissed or acknowledged this session — the
   * rest wait for the next launch. Required-updates are exempt: they block
   * regardless.
   */
  handledThisSession?: boolean;
}

export interface SelectAnnouncementResult {
  active: ActiveAnnouncement | null;
  /** Items that failed per-item validation and were dropped. */
  invalidItems: number;
  /** The envelope itself failed to parse. */
  parseError: boolean;
  /** Any valid item carries a time bound — callers re-evaluate on a timer. */
  hasSchedule: boolean;
}

function none(overrides?: Partial<SelectAnnouncementResult>) {
  return {
    active: null,
    invalidItems: 0,
    parseError: false,
    hasSchedule: false,
    ...overrides,
  };
}

function isInWindow(announcement: Announcement, now: number): boolean {
  if (announcement.startsAt && now < Date.parse(announcement.startsAt)) {
    return false;
  }
  if (announcement.endsAt && now > Date.parse(announcement.endsAt)) {
    return false;
  }
  return true;
}

export function selectAnnouncement(
  input: SelectAnnouncementInput,
): SelectAnnouncementResult {
  const {
    payload,
    now,
    appVersion,
    isDevBuild,
    dismissedIds,
    handledThisSession = false,
  } = input;

  if (isDevBuild || appVersion === null) return none();
  if (payload === undefined || payload === null) return none();

  const envelope = announcementsEnvelopeSchema.safeParse(payload);
  if (!envelope.success) return none({ parseError: true });

  let invalidItems = 0;
  const items: Announcement[] = [];
  for (const raw of envelope.data.announcements) {
    const item = announcementSchema.safeParse(raw);
    if (item.success) {
      items.push(item.data);
    } else {
      invalidItems++;
    }
  }

  const hasSchedule = items.some((item) => item.startsAt || item.endsAt);
  const eligible = items.filter((item) => isInWindow(item, now));

  const requiredUpdate = eligible.find(
    (item): item is Extract<Announcement, { kind: "required-update" }> =>
      item.kind === "required-update" &&
      isVersionNewer(item.minVersion, appVersion),
  );
  if (requiredUpdate) {
    return {
      active: { announcement: requiredUpdate, needsUpdate: true },
      invalidItems,
      parseError: false,
      hasSchedule,
    };
  }

  const announcement = handledThisSession
    ? undefined
    : eligible.find(
        (item): item is Extract<Announcement, { kind: "announcement" }> =>
          item.kind === "announcement" && !dismissedIds.has(item.id),
      );
  if (announcement) {
    return {
      active: {
        announcement,
        needsUpdate:
          announcement.minVersion !== undefined &&
          isVersionNewer(announcement.minVersion, appVersion),
      },
      invalidItems,
      parseError: false,
      hasSchedule,
    };
  }

  return none({ invalidItems, hasSchedule });
}
