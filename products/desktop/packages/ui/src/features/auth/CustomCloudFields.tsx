import { Input, Text } from "@posthog/quill";
import type { CustomCloudDraft } from "./useCustomCloud";

interface CustomCloudFieldsProps {
  draft: CustomCloudDraft;
  onChange: (patch: Partial<CustomCloudDraft>) => void;
  onBlur: () => void;
  error: string | null;
  disabled?: boolean;
}

export function CustomCloudFields({
  draft,
  onChange,
  onBlur,
  error,
  disabled = false,
}: CustomCloudFieldsProps) {
  return (
    <div className="flex w-full flex-col gap-2">
      <Input
        type="url"
        placeholder="https://posthog.example.com"
        aria-label="PostHog instance URL"
        value={draft.url}
        disabled={disabled}
        onChange={(event) => onChange({ url: event.target.value })}
        onBlur={onBlur}
      />
      <Input
        type="text"
        placeholder="OAuth client ID"
        aria-label="OAuth client ID"
        value={draft.oauthClientId}
        disabled={disabled}
        onChange={(event) => onChange({ oauthClientId: event.target.value })}
        onBlur={onBlur}
      />
      <Input
        type="url"
        placeholder="LLM gateway URL (optional)"
        aria-label="LLM gateway URL"
        value={draft.gatewayUrl}
        disabled={disabled}
        onChange={(event) => onChange({ gatewayUrl: event.target.value })}
        onBlur={onBlur}
      />
      {error && (
        <Text className="text-(--red-11) text-xs" role="alert">
          {error}
        </Text>
      )}
    </div>
  );
}
