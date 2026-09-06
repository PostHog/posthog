import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { MemberPicker } from "@posthog/ui/features/canvas/components/MemberPicker";
import {
  useChannelMembers,
  useSetChannelMembers,
} from "@posthog/ui/features/canvas/hooks/useChannelMembers";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { toast } from "@posthog/ui/primitives/toast";
import { useMemo, useState } from "react";

function sameSet(a: number[], b: number[]): boolean {
  if (a.length !== b.length) return false;
  const seen = new Set(a);
  return b.every((id) => seen.has(id));
}

/**
 * Manage a private space's members. Any member can add or remove others; the
 * creator is always kept, so their row has no remove control. Save sends the
 * full set and stays locked while the request is in flight.
 */
export function ManageMembersDialog({
  channel,
  open,
  onOpenChange,
}: {
  channel: Channel;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const creatorId = channel.createdBy?.id ?? null;
  const { members, isLoading } = useChannelMembers(open ? channel.id : null);
  const { setMembers, isSaving } = useSetChannelMembers(channel.id);

  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  // Seed the working set once per open, when the members have loaded. Guarded by
  // `seeded` so a later poll never clobbers the user's edits.
  const [wasOpen, setWasOpen] = useState(open);
  const [seeded, setSeeded] = useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setSeeded(false);
  }
  if (open && !seeded && !isLoading) {
    setSeeded(true);
    setSelectedIds(members.map((member) => member.id));
  }

  const initialIds = useMemo(
    () => members.map((member) => member.id),
    [members],
  );
  const isUnchanged = sameSet(selectedIds, initialIds);

  const submit = async (): Promise<void> => {
    if (isSaving || isUnchanged) return;
    try {
      await setMembers(selectedIds);
      onOpenChange(false);
    } catch (error) {
      toast.error("Couldn't update members", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isSaving) onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Members of {channel.name}</DialogTitle>
          <DialogDescription>
            Only members can see this private space. Anyone here can add or
            remove members.
          </DialogDescription>
        </DialogHeader>
        <DialogBody viewportClassName="flex flex-col gap-3">
          {isLoading ? (
            <p className="px-1 py-2 text-muted-foreground text-sm">
              Loading members…
            </p>
          ) : (
            <MemberPicker
              selectedIds={selectedIds}
              onChange={setSelectedIds}
              disabled={isSaving}
              lockedId={creatorId}
            />
          )}
        </DialogBody>
        <DialogFooter>
          <DialogClose
            render={
              <Button variant="outline" disabled={isSaving}>
                Cancel
              </Button>
            }
          />
          <Button
            variant="primary"
            loading={isSaving}
            disabled={isUnchanged}
            data-attr="save-space-members"
            onClick={() => void submit()}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
