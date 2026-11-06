import { CrownSimpleIcon } from "@phosphor-icons/react";
import type { PresenceTier } from "@posthog/core/canvas/presence";
import {
  AvatarGroup,
  cn,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import {
  type AvatarPerson,
  UserAvatar,
} from "@posthog/ui/features/auth/UserAvatar";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";

type AvatarSize = "lg" | "default" | "sm" | "xs";

/** A tier that draws something. `idle` faces don't show, so callers filter it. */
type ActiveTier = Exclude<PresenceTier, "idle">;

/** Matches the rows' own tooltip delay, so a face doesn't feel slower. */
const TOOLTIP_DELAY_MS = 200;

/**
 * The corner mark that turns a face into presence: a pulsing dot while the
 * person is working right now, a quiet one for a while after they step away.
 * The `ring-background` gap is what lifts it off the avatar the way a stacked
 * group's own gaps do.
 */
function PresenceDot({ tier }: { tier: ActiveTier }) {
  if (tier === "live") {
    return (
      <span className="absolute right-0 bottom-0 flex size-2 items-center justify-center">
        {/* The halo does the "live" work; a static dot alone reads as a badge. */}
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-75" />
        <span className="relative inline-flex size-1.5 rounded-full bg-primary ring-1 ring-background" />
      </span>
    );
  }
  return (
    <span className="absolute right-0 bottom-0 size-1.5 rounded-full bg-muted-foreground/70 ring-1 ring-background" />
  );
}

/**
 * One person's face with a presence mark and a name tooltip. Use this for a
 * single owner beside a row; the group below draws its own faces for a space.
 */
export function PresenceAvatar({
  user,
  tier,
  label,
  size = "xs",
  className,
}: {
  user: AvatarPerson | null | undefined;
  tier: ActiveTier;
  /** Overrides the name shown on hover; defaults to the user's display name. */
  label?: string;
  size?: AvatarSize;
  className?: string;
}) {
  const name = label ?? userDisplayName(user);
  return (
    <Tooltip disableHoverablePopup>
      <TooltipTrigger
        render={
          // `flex`, not `block`: quill's avatar is an inline-flex box, so a
          // block wrapper adds the line box's descender space under it and the
          // avatar rides high in a taller container.
          <span
            aria-label={name}
            role="img"
            className={cn("relative flex shrink-0", className)}
          >
            <UserAvatar size={size} user={user} />
            <PresenceDot tier={tier} />
          </span>
        }
      />
      <TooltipContent side="top" className="pointer-events-none select-none">
        {name}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * One face in a space's group: the person, a crown when they created the space,
 * and a live dot when they are working right now. Non-live people stay plain,
 * so the group reads as "who's here" and the dots pick out who's active.
 */
function GroupPerson({
  user,
  isLead,
  isLive,
}: {
  user: UserBasic;
  isLead: boolean;
  isLive: boolean;
}) {
  const name = userDisplayName(user);
  const label = isLead ? `${name} created this space` : name;
  return (
    <Tooltip disableHoverablePopup>
      <TooltipTrigger
        render={
          <span
            aria-label={label}
            role="img"
            className="relative flex shrink-0"
          >
            <UserAvatar size="xs" user={user} />
            {isLead && (
              // Top-left rather than top-right: the stack tucks each face behind
              // the one after it, so the creator's right corner is under its
              // neighbour and a crown there is a sliver nobody can read. The live
              // dot takes the bottom-right, so the two never collide.
              <span className="-top-1 -left-1 absolute rounded-full bg-background p-px">
                <CrownSimpleIcon
                  size={9}
                  weight="fill"
                  className="block text-primary"
                />
              </span>
            )}
            {isLive && <PresenceDot tier="live" />}
          </span>
        }
      />
      <TooltipContent side="top" className="pointer-events-none select-none">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * A space's people, stacked so each face tucks behind the one after it — which
 * is what `reverse` gives, and why the lead's crown sits on the left corner of
 * its avatar rather than the right. Live people wear a pulsing dot.
 */
export function PresenceAvatars({
  people,
  liveUuids,
  leadUuid,
  className,
}: {
  people: UserBasic[];
  /** Of `people`, the uuids working right now — their faces pulse. */
  liveUuids?: ReadonlySet<string>;
  /** The person to mark with a crown (a space's creator), if shown. */
  leadUuid?: string;
  className?: string;
}) {
  if (people.length === 0) return null;
  return (
    <TooltipProvider delay={TOOLTIP_DELAY_MS}>
      <AvatarGroup stacked reverse size="xs" className={className}>
        {people.map((user) => (
          <GroupPerson
            key={user.uuid}
            user={user}
            isLead={user.uuid === leadUuid}
            isLive={liveUuids?.has(user.uuid) ?? false}
          />
        ))}
      </AvatarGroup>
    </TooltipProvider>
  );
}
