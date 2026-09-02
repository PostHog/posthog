import { ArrowLeft, CaretDown, CaretRight, Plus } from "@phosphor-icons/react";
import type { McpAuthType } from "@posthog/api-client/posthog-client";
import {
  buildCustomServerRequest,
  canSubmitCustomServer,
} from "@posthog/core/mcp-servers/customServerForm";
import {
  Button,
  Flex,
  Select,
  Spinner,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useCallback, useState } from "react";

interface AddCustomServerFormProps {
  pending: boolean;
  onBack: () => void;
  onSubmit: (values: {
    name: string;
    url: string;
    description: string;
    auth_type: McpAuthType;
    api_key?: string;
    client_id?: string;
    client_secret?: string;
  }) => void;
  /** Prefill the form (e.g. the agent builder's connect_mcp punch-out supplies a
   *  suggested name/url). The user can still edit every field before connecting. */
  initialValues?: {
    name?: string;
    url?: string;
    description?: string;
    auth_type?: McpAuthType;
  };
  /** Hide the in-form Back button + title/description — for when a host chrome
   *  (e.g. a dialog) already provides them. */
  hideHeader?: boolean;
}

export function AddCustomServerForm({
  pending,
  onBack,
  onSubmit,
  initialValues,
  hideHeader = false,
}: AddCustomServerFormProps) {
  const [name, setName] = useState(initialValues?.name ?? "");
  const [url, setUrl] = useState(initialValues?.url ?? "");
  const [description, setDescription] = useState(
    initialValues?.description ?? "",
  );
  const [authType, setAuthType] = useState<McpAuthType>(
    initialValues?.auth_type ?? "oauth",
  );
  const [apiKey, setApiKey] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const canSubmit = canSubmitCustomServer({ name, url }) && !pending;

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!canSubmit) return;
      onSubmit(
        buildCustomServerRequest({
          name,
          url,
          description,
          authType,
          apiKey,
          clientId,
          clientSecret,
        }),
      );
    },
    [
      canSubmit,
      name,
      url,
      description,
      authType,
      apiKey,
      clientId,
      clientSecret,
      onSubmit,
    ],
  );

  return (
    <form onSubmit={handleSubmit}>
      <Flex direction="column" gap="4" className="min-w-0">
        {!hideHeader && (
          <>
            <Flex align="center" gap="2">
              <Button
                variant="ghost"
                color="gray"
                size="1"
                type="button"
                onClick={onBack}
              >
                <ArrowLeft size={12} />
                Back
              </Button>
            </Flex>

            <Flex direction="column" gap="1">
              <Text className="font-bold text-xl">Add MCP server</Text>
              <Text color="gray" className="text-sm">
                Connect a custom MCP server by URL. Tools appear in your agent
                once the connection is verified.
              </Text>
            </Flex>
          </>
        )}

        <Flex direction="column" gap="3">
          <Flex direction="column" gap="1">
            <Text className="font-medium text-sm">Name</Text>
            <Text color="gray" className="text-[13px]">
              A short label shown in your sidebar and tool calls.
            </Text>
            <TextField.Root
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My team's wiki"
              autoFocus
            />
          </Flex>

          <Flex direction="column" gap="1">
            <Text className="font-medium text-sm">Server URL</Text>
            <Text color="gray" className="text-[13px]">
              HTTPS endpoint or streamable URL.
            </Text>
            <TextField.Root
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://mcp.example.com/stream"
              spellCheck={false}
            />
          </Flex>

          <Flex direction="column" gap="1">
            <Text className="font-medium text-sm">Description</Text>
            <TextField.Root
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this server do?"
            />
          </Flex>

          <Flex direction="column" gap="1">
            <Text className="font-medium text-sm">Auth type</Text>
            <Select.Root
              value={authType}
              onValueChange={(val) => {
                setAuthType(val as McpAuthType);
                if (val !== "api_key") setApiKey("");
              }}
            >
              <Select.Trigger />
              <Select.Content>
                <Select.Item value="oauth">OAuth</Select.Item>
                <Select.Item value="api_key">API key</Select.Item>
              </Select.Content>
            </Select.Root>
          </Flex>

          {authType === "api_key" && (
            <Flex direction="column" gap="1">
              <Text className="font-medium text-sm">API key</Text>
              <TextField.Root
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Enter API key"
                type="password"
              />
            </Flex>
          )}

          {authType === "oauth" && (
            <>
              <Button
                type="button"
                variant="ghost"
                color="gray"
                size="1"
                onClick={() => setShowAdvanced((v) => !v)}
                className="self-start"
              >
                {showAdvanced ? (
                  <CaretDown size={11} weight="bold" />
                ) : (
                  <CaretRight size={11} weight="bold" />
                )}
                Optional — authentication
              </Button>
              {showAdvanced && (
                <Flex direction="column" gap="3" className="pl-4">
                  <Flex direction="column" gap="1">
                    <Text className="font-medium text-sm">Client ID</Text>
                    <Text color="gray" className="text-[13px]">
                      OAuth client identifier, if the server requires it.
                    </Text>
                    <TextField.Root
                      value={clientId}
                      onChange={(e) => setClientId(e.target.value)}
                      placeholder="your-oauth-client-id"
                      spellCheck={false}
                    />
                  </Flex>
                  <Flex direction="column" gap="1">
                    <Text className="font-medium text-sm">Client secret</Text>
                    <Text color="gray" className="text-[13px]">
                      Stored encrypted — never logged.
                    </Text>
                    <TextField.Root
                      value={clientSecret}
                      onChange={(e) => setClientSecret(e.target.value)}
                      placeholder="••••••••••••••••"
                      type="password"
                      spellCheck={false}
                    />
                  </Flex>
                </Flex>
              )}
            </>
          )}
        </Flex>

        <Flex gap="2" justify="end">
          <Button
            type="button"
            variant="soft"
            color="gray"
            onClick={onBack}
            disabled={pending}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={!canSubmit}>
            {pending ? <Spinner size="1" /> : <Plus size={12} />}
            Add server
          </Button>
        </Flex>
      </Flex>
    </form>
  );
}
