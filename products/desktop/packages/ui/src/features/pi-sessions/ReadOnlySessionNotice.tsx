import { Text } from "@posthog/quill";

export function ReadOnlySessionNotice() {
  return (
    <div className="rounded-md border border-border bg-muted px-3 py-4 text-center">
      <Text className="text-muted-foreground">
        You can view this session, but only its owner can send messages.
      </Text>
    </div>
  );
}
