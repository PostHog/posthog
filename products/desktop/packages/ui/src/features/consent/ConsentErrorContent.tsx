import { Button, Text } from "@posthog/quill";

interface ConsentErrorContentProps {
  onRetry: () => void;
}

export function ConsentErrorContent({ onRetry }: ConsentErrorContentProps) {
  return (
    <div className="flex w-full max-w-[520px] flex-col gap-4 text-center">
      <h1 className="font-bold text-2xl text-foreground">
        Could not check organization consent
      </h1>
      <Text size="sm" variant="muted">
        Check your connection and try again. If this keeps happening, contact
        support.
      </Text>
      <Button variant="primary" size="lg" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}
