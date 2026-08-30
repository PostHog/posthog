import { ArrowSquareOut, ArrowsClockwise, Camera } from "@phosphor-icons/react";
import { avatarColor } from "@posthog/core/auth/avatarColor";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Button,
  cn,
} from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import type { AvatarPerson } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useGravatarUrl } from "@posthog/ui/features/auth/useGravatarUrl";
import { getUserInitials } from "@posthog/ui/features/auth/userInitials";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { useCallback, useState } from "react";

const GRAVATAR_MANAGE_URL = "https://gravatar.com/profile/avatars";

// The avatar renders at 72px; ask Gravatar for 2x so it stays sharp on retina.
const GRAVATAR_IMAGE_SIZE = 144;

export type ProfilePictureStatus = "checking" | "found" | "missing";

type ImageLoadingStatus = "idle" | "loading" | "loaded" | "error";

interface ProfilePictureRowProps {
  user: AvatarPerson;
  imageUrl?: string;
  status: ProfilePictureStatus;
  onImageLoadingStatusChange: (status: ImageLoadingStatus) => void;
  onRefresh: () => void;
  onOpenGravatar: () => void;
}

function profilePictureDescription(
  status: ProfilePictureStatus,
  email: string,
): string {
  switch (status) {
    case "checking":
      return `Checking Gravatar for ${email}`;
    case "found":
      return `Comes from Gravatar, matched to ${email}. Change it there, then refresh to see it here.`;
    case "missing":
      return `No picture yet. Add one on Gravatar for ${email} and it shows here and anywhere teammates see you.`;
  }
}

export function ProfilePictureRow({
  user,
  imageUrl,
  status,
  onImageLoadingStatusChange,
  onRefresh,
  onOpenGravatar,
}: ProfilePictureRowProps) {
  const name = userDisplayName(user);
  const color = avatarColor(user.uuid ?? user.email ?? name);
  const hasPicture = status === "found";
  const gravatarActionLabel = hasPicture
    ? "Change on Gravatar"
    : "Add on Gravatar";

  return (
    <div className="flex flex-wrap items-center gap-4 px-3.5 py-3">
      <button
        type="button"
        aria-label={`${gravatarActionLabel} (opens gravatar.com)`}
        data-attr="settings-profile-picture-avatar"
        onClick={onOpenGravatar}
        className="group relative shrink-0 cursor-pointer rounded-(--radius-3) border-0 bg-transparent p-0 focus-visible:outline-(--accent-8) focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <Avatar
          className={cn(
            "rounded-(--radius-3) font-medium text-xl [--avatar-size:4.5rem]",
            status === "missing" &&
              "outline-dashed outline-(--gray-8) outline-1 outline-offset-2",
          )}
        >
          {imageUrl ? (
            <AvatarImage
              src={imageUrl}
              alt={name}
              onLoadingStatusChange={onImageLoadingStatusChange}
            />
          ) : null}
          <AvatarFallback
            style={{ backgroundColor: color.bg, color: color.text }}
          >
            {getUserInitials(user)}
          </AvatarFallback>
        </Avatar>
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-(--radius-3) bg-black/55 text-white opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none"
        >
          <Camera size={20} weight="fill" />
        </span>
      </button>

      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="font-medium text-[13px] text-foreground leading-snug">
          Profile picture
        </span>
        <span className="text-[12px] text-muted-foreground leading-snug">
          {profilePictureDescription(status, user.email ?? "your email")}
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <Tooltip content="Check Gravatar again">
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Check Gravatar again"
            data-attr="settings-profile-picture-refresh"
            disabled={status === "checking"}
            onClick={onRefresh}
          >
            <ArrowsClockwise
              size={12}
              className={cn(
                status === "checking" && "motion-safe:animate-spin",
              )}
            />
          </Button>
        </Tooltip>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-attr="settings-profile-picture-gravatar"
          onClick={onOpenGravatar}
        >
          {gravatarActionLabel}
          <ArrowSquareOut size={12} />
        </Button>
      </div>
    </div>
  );
}

interface AccountSettingsViewProps extends ProfilePictureRowProps {
  accountUrl: string | null;
}

export function AccountSettingsView({
  accountUrl,
  ...pictureProps
}: AccountSettingsViewProps) {
  return (
    <SettingsSection
      label="Account"
      description="Who you are signed in as and how you appear to teammates"
    >
      <SettingsCard>
        <ProfilePictureRow {...pictureProps} />
        <SettingsCardRow
          label="PostHog account"
          description="Account and billing details are managed on PostHog"
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!accountUrl}
            onClick={() => {
              if (accountUrl) window.open(accountUrl, "_blank");
            }}
          >
            Manage
            <ArrowSquareOut size={12} />
          </Button>
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}

export function AccountSection() {
  const client = useOptionalAuthenticatedClient();
  const { data: user } = useCurrentUser({ client });
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const gravatarUrl = useGravatarUrl(user?.email, GRAVATAR_IMAGE_SIZE);

  const [status, setStatus] = useState<ProfilePictureStatus>("checking");
  const [refreshedAt, setRefreshedAt] = useState<number | null>(null);

  const handleImageLoadingStatusChange = useCallback(
    (imageStatus: ImageLoadingStatus) => {
      if (imageStatus === "loaded") setStatus("found");
      else if (imageStatus === "error") setStatus("missing");
      else setStatus("checking");
    },
    [],
  );

  // A new query string forces the browser past its cached 404 or stale image
  // after the person uploads a picture on Gravatar.
  const handleRefresh = useCallback(() => {
    setStatus("checking");
    setRefreshedAt(Date.now());
  }, []);

  const handleOpenGravatar = useCallback(() => {
    window.open(GRAVATAR_MANAGE_URL, "_blank");
  }, []);

  if (!user) return null;

  const imageUrl =
    gravatarUrl && refreshedAt
      ? `${gravatarUrl}&_=${refreshedAt}`
      : gravatarUrl;

  return (
    <AccountSettingsView
      user={user}
      imageUrl={imageUrl}
      status={status}
      onImageLoadingStatusChange={handleImageLoadingStatusChange}
      onRefresh={handleRefresh}
      onOpenGravatar={handleOpenGravatar}
      accountUrl={buildPostHogUrl("/settings/user", cloudRegion)}
    />
  );
}
