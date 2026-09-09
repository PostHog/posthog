import { InfoIcon } from "@phosphor-icons/react";
import { Input, Text } from "@posthog/quill";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import type { CustomCloudDraft } from "./useCustomCloud";

const FIELDS: {
  key: keyof CustomCloudDraft;
  type: "url" | "text" | "password";
  placeholder: string;
  label: string;
  help: string;
}[] = [
  {
    key: "url",
    type: "url",
    placeholder: "https://posthog.example.com",
    label: "PostHog instance URL",
    help: "The address of your PostHog instance. Sign-in, the API, and links use it.",
  },
  {
    key: "oauthClientId",
    type: "text",
    placeholder: "OAuth client ID",
    label: "OAuth client ID",
    help: "The client ID of the OAuth application on that instance. Make the application in Django admin, with the redirect URI posthog-code://callback.",
  },
  {
    key: "gatewayUrl",
    type: "url",
    placeholder: "LLM gateway URL (optional)",
    label: "LLM gateway URL",
    help: "The LLM gateway for agent runs. Give a value only if your instance has its own gateway. Empty keeps the US gateway.",
  },
  {
    key: "gatewayToken",
    type: "password",
    placeholder: "Personal API key for the gateway (optional)",
    label: "Personal API key for the gateway",
    help: "A personal API key from PostHog Cloud. Give a value if you use the US or EU gateway, because that gateway does not know your instance. The app keeps the key encrypted.",
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
      {FIELDS.map(({ key, type, placeholder, label, help }) => (
        <div key={key} className="flex items-center gap-2">
          <Input
            className="flex-1"
            type={type}
            autoComplete="off"
            placeholder={placeholder}
            aria-label={label}
            value={draft[key]}
            disabled={disabled}
            onChange={(event) => onChange({ [key]: event.target.value })}
            onBlur={onBlur}
          />
          <Tooltip
            content={<span className="block max-w-[240px]">{help}</span>}
            side="right"
          >
            <button
              type="button"
              aria-label={`About ${label}`}
              className="shrink-0 cursor-help text-(--gray-10) hover:text-(--gray-12)"
            >
              <InfoIcon size={14} />
            </button>
          </Tooltip>
        </div>
      ))}
      {error && (
        <Text className="text-(--red-11) text-xs" role="alert">
          {error}
        </Text>
      )}
    </div>
  );
}
