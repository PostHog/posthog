import { ArrowSquareOut, ArrowsClockwise, Camera } from "@phosphor-icons/react";
import { avatarColor } from "@posthog/core/auth/avatarColor";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import { Avatar, AvatarFallback, Button, cn } from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import type { AvatarPerson } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useGravatarUrl } from "@posthog/ui/features/auth/useGravatarUrl";
import {
  type ImageProbeResult,
  useImageProbe,
} from "@posthog/ui/features/auth/useImageProbe";
import { getUserInitials } from "@posthog/ui/features/auth/userInitials";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { Spin } from "@posthog/ui/primitives/Spinner";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { useCallback, useState } from "react";

const GRAVATAR_MANAGE_URL = "https://gravatar.com/profile/avatars";
const GRAVATAR_IMAGE_SIZE = 144;

type ProfilePictureStatus = "unknown" | "found" | "missing";

interface ProfilePictureRowProps {
  user: AvatarPerson;
  imageUrl?: string;
  status: ProfilePictureStatus;
  checking: boolean;
  onRefresh: () => void;
  onOpenGravatar: () => void;
}

function profilePictureDescription(
  status: ProfilePictureStatus,
  email: string,
): string {
  switch (status) {
    case "unknown":
      return `Checking Gravatar for ${email}`;
    case "found":
      return `Comes from Gravatar, matched to ${email}. Change it there, then refresh to see it here.`;
    case "missing":
      return `No picture yet. Add one on Gravatar for ${email} and it shows here and anywhere teammates see you.`;
  }
}

function probeStatus(result: ImageProbeResult): ProfilePictureStatus {
  switch (result) {
    case "loaded":
      return "found";
    case "failed":
      return "missing";
    case "unknown":
      return "unknown";
  }
}

function ProfilePictureRow({
  user,
  imageUrl,
  status,
  checking,
  onRefresh,
  onOpenGravatar,
}: ProfilePictureRowProps) {
  const name = userDisplayName(user);
  const color = avatarColor(user.uuid ?? user.email ?? name);
  const gravatarActionLabel =
    status === "found" ? "Change on Gravatar" : "Add on Gravatar";

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
          <AvatarFallback
            style={{ backgroundColor: color.bg, color: color.text }}
          >
            {getUserInitials(user)}
          </AvatarFallback>
          {imageUrl ? (
            <img
              src={imageUrl}
              alt=""
              className="absolute inset-0 size-full object-cover"
            />
          ) : null}
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
        <span className="min-h-[2lh] text-[12px] text-muted-foreground leading-snug">
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
            disabled={checking}
            onClick={onRefresh}
          >
            <Spin spinning={checking} className="motion-reduce:animate-none">
              <ArrowsClockwise size={12} />
            </Spin>
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
  const [refreshedAt, setRefreshedAt] = useState<number | null>(null);

  const candidateUrl =
    gravatarUrl && refreshedAt
      ? `${gravatarUrl}&_=${refreshedAt}`
      : gravatarUrl;
  const probe = useImageProbe(candidateUrl);

  const handleRefresh = useCallback(() => {
    setRefreshedAt(Date.now());
  }, []);

  const handleOpenGravatar = useCallback(() => {
    window.open(GRAVATAR_MANAGE_URL, "_blank");
  }, []);

  if (!user) return null;

  return (
    <AccountSettingsView
      user={user}
      imageUrl={probe.url}
      status={probeStatus(probe.result)}
      checking={probe.loading || !candidateUrl}
      onRefresh={handleRefresh}
      onOpenGravatar={handleOpenGravatar}
      accountUrl={buildPostHogUrl("/settings/user", cloudRegion)}
    />
  );
}
