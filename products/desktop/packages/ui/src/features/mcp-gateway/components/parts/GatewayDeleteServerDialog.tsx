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
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="sm:max-w-[450px]">
        <AlertDialogHeader>
          <AlertDialogTitle>Delete MCP server</AlertDialogTitle>
          <AlertDialogDescription>
            {deletesForEveryone ? (
              <>
                Delete <span className="font-bold">{serverName}</span> for
                everyone? This disconnects every teammate and removes the custom
                server from the team gateway.
              </>
            ) : (
              <>
                Delete <span className="font-bold">{serverName}</span> for you?
                This removes its tools from your agent without removing a team
                server for anyone else.
              </>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose
            render={<Button variant="outline" disabled={pending} />}
          >
            Cancel
          </AlertDialogClose>
          <Button
            variant="destructive-outline"
            disabled={pending}
            loading={pending}
            onClick={onConfirm}
          >
            Delete
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
