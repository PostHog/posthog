import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";

interface GatewayDeleteServerDialogProps {
  open: boolean;
  serverName: string;
  deletesForEveryone: boolean;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export function GatewayDeleteServerDialog({
  open,
  serverName,
  deletesForEveryone,
  pending,
  onOpenChange,
  onConfirm,
}: GatewayDeleteServerDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={() => undefined}>
      <AlertDialogContent className="max-w-[450px]">
        <AlertDialogHeader>
          <AlertDialogTitle>Delete MCP server</AlertDialogTitle>
          <AlertDialogDescription>
            {deletesForEveryone ? (
              <>
                Delete <strong>{serverName}</strong> for everyone? This
                disconnects every teammate and removes the custom server from
                the team gateway.
              </>
            ) : (
              <>
                Delete <strong>{serverName}</strong> for you? This removes its
                tools from your agent without removing a team server for anyone
                else.
              </>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button
            variant="outline"
            disabled={pending}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="destructive-outline"
            loading={pending}
            disabled={pending}
            onClick={onConfirm}
          >
            Delete
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
