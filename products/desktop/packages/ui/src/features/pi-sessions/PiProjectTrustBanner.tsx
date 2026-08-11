import { Warning } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { Flex, Text } from "@radix-ui/themes";
import { useState } from "react";

interface PiProjectTrustBannerProps {
  trusted: boolean;
  disabled: boolean;
  pending: boolean;
  onTrust: () => Promise<void>;
  onRevoke: () => Promise<void>;
}

export function PiProjectTrustBanner({
  trusted,
  disabled,
  pending,
  onTrust,
  onRevoke,
}: PiProjectTrustBannerProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);

  const trust = async () => {
    await onTrust();
    setConfirmOpen(false);
  };

  return (
    <>
      <Flex
        align="center"
        gap="2"
        justify="between"
        className="mb-2 rounded-md border border-border bg-surface-secondary px-3 py-2"
      >
        <Flex align="center" gap="2" className="min-w-0">
          <Warning size={16} className="shrink-0 text-warning" />
          <Text size="1" color="gray">
            {trusted
              ? "Project-local Pi resources are enabled. Changing trust restarts Pi."
              : "Project-local Pi extensions, settings, and skills are disabled."}
          </Text>
        </Flex>
        {trusted ? (
          <Button
            size="sm"
            variant="outline"
            disabled={disabled || pending}
            loading={pending}
            onClick={() => void onRevoke()}
          >
            Revoke trust
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={disabled || pending}
            onClick={() => setConfirmOpen(true)}
          >
            Trust repository
          </Button>
        )}
      </Flex>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Trust this repository?</AlertDialogTitle>
            <AlertDialogDescription>
              Project extensions run arbitrary code with your full user
              permissions. They can access files and credentials, start
              processes, and use the network. Only continue after reviewing the
              complete source and dependency tree.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={<Button variant="outline">Cancel</Button>}
            />
            <Button
              variant="destructive"
              loading={pending}
              disabled={disabled || pending}
              onClick={() => void trust()}
            >
              Trust and restart Pi
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
