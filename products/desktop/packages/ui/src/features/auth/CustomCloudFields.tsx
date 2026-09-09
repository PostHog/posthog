import { Input, Text } from "@posthog/quill";
import type { CustomCloudDraft } from "./useCustomCloud";

const FIELDS: {
  key: keyof CustomCloudDraft;
  type: "url" | "text" | "password";
  placeholder: string;
  label: string;
}[] = [
  {
    key: "url",
    type: "url",
    placeholder: "https://posthog.example.com",
    label: "PostHog instance URL",
  },
  {
    key: "oauthClientId",
    type: "text",
    placeholder: "OAuth client ID",
    label: "OAuth client ID",
  },
  {
    key: "gatewayUrl",
    type: "url",
    placeholder: "LLM gateway URL (optional)",
    label: "LLM gateway URL",
  },
  {
    key: "gatewayToken",
    type: "password",
    placeholder: "Personal API key for the gateway (optional)",
    label: "Personal API key for the gateway",
  },
];

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
      {FIELDS.map(({ key, type, placeholder, label }) => (
        <Input
          key={key}
          type={type}
          autoComplete="off"
          placeholder={placeholder}
          aria-label={label}
          value={draft[key]}
          disabled={disabled}
          onChange={(event) => onChange({ [key]: event.target.value })}
          onBlur={onBlur}
        />
      ))}
      {error && (
        <Text className="text-(--red-11) text-xs" role="alert">
          {error}
        </Text>
      )}
    </div>
  );
}
