import { AlertDialog, Button, Flex, Spinner, Text } from "@radix-ui/themes";

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
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Content maxWidth="450px">
        <AlertDialog.Title>Delete MCP server</AlertDialog.Title>
        <AlertDialog.Description className="text-sm">
          {deletesForEveryone ? (
            <>
              Delete <Text className="font-bold">{serverName}</Text> for
              everyone? This disconnects every teammate and removes the custom
              server from the team gateway.
            </>
          ) : (
            <>
              Delete <Text className="font-bold">{serverName}</Text> for you?
              This removes its tools from your agent without removing a team
              server for anyone else.
            </>
          )}
        </AlertDialog.Description>
        <Flex gap="3" mt="4" justify="end">
          <AlertDialog.Cancel>
            <Button variant="soft" color="gray" disabled={pending}>
              Cancel
            </Button>
          </AlertDialog.Cancel>
          <AlertDialog.Action>
            <Button
              variant="solid"
              color="red"
              disabled={pending}
              onClick={onConfirm}
            >
              {pending ? <Spinner size="1" /> : null}
              Delete
            </Button>
          </AlertDialog.Action>
        </Flex>
      </AlertDialog.Content>
    </AlertDialog.Root>
  );
}
