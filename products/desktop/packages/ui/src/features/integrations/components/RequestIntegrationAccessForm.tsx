import { Button, Text, Textarea } from "@posthog/quill";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

const MAX_REASON_LENGTH = 2000;

interface RequestIntegrationAccessFormProps {
  projectId: number;
  kind: "github" | "slack";
  integrationName: string;
}

/**
 * The PostHog-side handoff for members who can't connect an integration themselves: the
 * request emails the project's admins, who can connect it in either the web app or Desktop.
 */
export function RequestIntegrationAccessForm({
  projectId,
  kind,
  integrationName,
}: RequestIntegrationAccessFormProps) {
  const client = useAuthenticatedClient();
  const [reason, setReason] = useState("");
  const [sent, setSent] = useState(false);

  const request = useMutation({
    mutationFn: async () => {
      await client.requestIntegrationAccess(projectId, {
        kind,
        reason: reason.trim(),
      });
    },
    onSuccess: () => {
      setSent(true);
      toast.success("Request sent. A project admin will get an email.");
    },
    onError: (error) => {
      toast.error(
        error instanceof Error ? error.message : "Couldn't send the request.",
      );
    },
  });

  if (sent) {
    return (
      <Text size="xs" variant="muted">
        Request sent. A project admin will get an email and can connect{" "}
        {integrationName} for this project.
      </Text>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <Text size="xs" variant="muted">
        Connecting {integrationName} needs a project admin. Tell them why you
        need it and we'll email them.
      </Text>
      <Textarea
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        maxLength={MAX_REASON_LENGTH}
        rows={2}
        placeholder="e.g. I'm setting up Self-driving for the mobile repositories."
        disabled={request.isPending}
      />
      <div className="flex">
        <Button
          type="button"
          variant="primary"
          size="sm"
          onClick={() => request.mutate()}
          loading={request.isPending}
          disabled={request.isPending || reason.trim().length === 0}
        >
          Ask a project admin
        </Button>
      </div>
    </div>
  );
}
