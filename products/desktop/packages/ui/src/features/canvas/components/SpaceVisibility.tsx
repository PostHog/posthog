import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import {
  type Channel,
  useChannelMutations,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  SettingsCard,
  SettingsCardRow,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { toast } from "@posthog/ui/primitives/toast";
import { useState } from "react";

type SharedType = "public" | "private";

const VISIBILITY: Record<
  SharedType,
  {
    label: string;
    description: string;
    action: string;
    confirmTitle: string;
    confirmBody: string;
  }
> = {
  public: {
    label: "Public",
    description: "Everyone in the project can see this space.",
    action: "Make private",
    confirmTitle: "Make this space private?",
    confirmBody:
      "Only you and the creator keep access. Other people lose access until you add them as members.",
  },
  private: {
    label: "Private",
    description: "Only members can see this space.",
    action: "Make public",
    confirmTitle: "Make this space public?",
    confirmBody:
      "Everyone in the project gains access to this space and its sessions. The member list is removed.",
  },
};

function oppositeOf(type: SharedType): SharedType {
  return type === "public" ? "private" : "public";
}

export function SpaceVisibility({
  channel,
}: {
  channel: Channel & { channelType: SharedType };
}) {
  const { updateChannelType, isUpdatingChannelType } = useChannelMutations();
  const [confirming, setConfirming] = useState(false);
  const current = VISIBILITY[channel.channelType];
  const canChange = channel.systemRole !== "general";

  const confirm = async () => {
    try {
      await updateChannelType(channel.id, oppositeOf(channel.channelType));
      setConfirming(false);
    } catch (error) {
      toast.error("Couldn't change who can see this space. Try again.", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };

  return (
    <>
      <SettingsCard>
        <SettingsCardRow
          label={current.label}
          description={current.description}
        >
          {canChange && (
            <Button
              variant="outline"
              size="sm"
              disabled={isUpdatingChannelType}
              onClick={() => setConfirming(true)}
            >
              {current.action}
            </Button>
          )}
        </SettingsCardRow>
      </SettingsCard>
      <AlertDialog
        open={confirming}
        onOpenChange={(next) => {
          if (!next && !isUpdatingChannelType) setConfirming(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{current.confirmTitle}</AlertDialogTitle>
            <AlertDialogDescription>
              {current.confirmBody}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirming(false)}
              disabled={isUpdatingChannelType}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => void confirm()}
              loading={isUpdatingChannelType}
              disabled={isUpdatingChannelType}
            >
              {current.action}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
