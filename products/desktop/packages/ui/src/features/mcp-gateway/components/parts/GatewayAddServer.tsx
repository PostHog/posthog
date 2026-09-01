import { ArrowLeft, CaretRight, Check } from "@phosphor-icons/react";
import {
  buildGatewayInstallRequest,
  canSubmitGatewayServer,
  GATEWAY_ADD_SERVER_DEFAULTS,
  type GatewayAddServerValues,
} from "@posthog/core/mcp-gateway/gatewayAddServer";
import { isValidMcpUrl } from "@posthog/core/mcp-servers/customServerForm";
import { AgentScopeToggle } from "@posthog/ui/features/mcp-gateway/components/parts/AgentScopeToggle";
import type { GatewayRoute } from "@posthog/ui/features/mcp-gateway/gatewayRoute";
import { useRegisterGatewayServer } from "@posthog/ui/features/mcp-gateway/hooks/useRegisterGatewayServer";
import {
  Button,
  Flex,
  Heading,
  Select,
  Spinner,
  Switch,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import { type FormEvent, useState } from "react";

interface GatewayAddServerProps {
  isAdmin: boolean;
  canManageAgentAccess: boolean;
  onNavigate: (route: GatewayRoute) => void;
}

/** Register a custom MCP server with the gateway. */
export function GatewayAddServer({
  isAdmin,
  canManageAgentAccess,
  onNavigate,
}: GatewayAddServerProps) {
  const [values, setValues] = useState<GatewayAddServerValues>(
    GATEWAY_ADD_SERVER_DEFAULTS,
  );
  const [showKey, setShowKey] = useState(false);
  const [optionalOpen, setOptionalOpen] = useState(false);

  const { register, registerPending } = useRegisterGatewayServer();

  const set = <K extends keyof GatewayAddServerValues>(
    key: K,
    value: GatewayAddServerValues[K],
  ) => setValues((previous) => ({ ...previous, [key]: value }));

  const urlInvalid = values.url.trim() !== "" && !isValidMcpUrl(values.url);
  const canSave = canSubmitGatewayServer(values);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSave || registerPending) return;
    const request = buildGatewayInstallRequest(values, {
      isAdmin,
      canManageAgentAccess,
    });
    register(
      { request },
      {
        onSuccess: (result) => {
          if (result.created) {
            onNavigate({ view: "server", serverId: result.created.id });
          }
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="min-w-0 max-w-[640px]">
      <Flex direction="column" gap="4">
        <Flex align="center" gap="2">
          <Button
            type="button"
            variant="ghost"
            color="gray"
            size="1"
            onClick={() => onNavigate({ view: "servers" })}
          >
            <ArrowLeft size={12} />
            Back to servers
          </Button>
        </Flex>

        <Flex direction="column" gap="1">
          <Heading className="font-bold text-xl">Add a custom server</Heading>
          <Text color="gray" className="text-sm">
            Register an MCP server with the gateway. Every call routes through
            the gateway, so tool policies, approvals and the audit log apply
            from the first request.
          </Text>
        </Flex>

        <SectionHeader label="Server" />
        <Flex direction="column" gap="3">
          <Field label="Name">
            <TextField.Root
              value={values.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="e.g. Internal Wiki"
              autoFocus
            />
          </Field>
          <Field label="Server URL">
            <TextField.Root
              value={values.url}
              onChange={(e) => set("url", e.target.value)}
              placeholder="https://mcp.example.com/sse"
              spellCheck={false}
              className="font-mono"
            />
            {urlInvalid && (
              <Text color="red" className="text-xs">
                Enter a full URL, like https://mcp.example.com
              </Text>
            )}
          </Field>
          <Field
            label="Description"
            hint="Shown on the server card so members and agents know what it's for."
          >
            <TextArea
              value={values.description}
              onChange={(e) => set("description", e.target.value)}
              placeholder="What this server does and when teammates should reach for it"
            />
          </Field>
        </Flex>

        <SectionHeader label="Authentication" />
        <Flex direction="column" gap="3">
          <Field
            label="Type"
            hint={
              values.authType === "oauth"
                ? "Each caller signs in with the provider. The gateway stores and refreshes their tokens."
                : "Connect with an API key. The key is encrypted at rest and never exposed."
            }
          >
            <Select.Root
              value={values.authType}
              onValueChange={(value) =>
                set("authType", value as GatewayAddServerValues["authType"])
              }
            >
              <Select.Trigger />
              <Select.Content>
                <Select.Item value="oauth">
                  OAuth — each caller signs in
                </Select.Item>
                <Select.Item value="api_key">API key</Select.Item>
              </Select.Content>
            </Select.Root>
          </Field>

          {values.authType === "api_key" && (
            <Field
              label="API key"
              hint="Encrypted at rest and never logged or exposed."
            >
              <TextField.Root
                value={values.apiKey}
                onChange={(e) => set("apiKey", e.target.value)}
                type={showKey ? "text" : "password"}
                placeholder="sk-…"
                spellCheck={false}
                className="font-mono"
              >
                <TextField.Slot side="right">
                  <Button
                    type="button"
                    variant="ghost"
                    color="gray"
                    size="1"
                    onClick={() => setShowKey((value) => !value)}
                  >
                    {showKey ? "Hide" : "Show"}
                  </Button>
                </TextField.Slot>
              </TextField.Root>
            </Field>
          )}

          {values.authType === "oauth" && (
            <div className="rounded-md border border-gray-5 bg-gray-2">
              <button
                type="button"
                onClick={() => setOptionalOpen((value) => !value)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left"
              >
                <CaretRight
                  size={10}
                  weight="bold"
                  className={`shrink-0 text-gray-10 transition-transform ${optionalOpen ? "rotate-90" : ""}`}
                />
                <Text className="font-medium text-sm">Optional</Text>
                <Text color="gray" className="text-xs">
                  Client ID &amp; secret — only if the provider doesn't support
                  dynamic client registration
                </Text>
              </button>
              {optionalOpen && (
                <Flex gap="3" className="px-3 pb-3">
                  <Field label="Client ID" className="flex-1">
                    <TextField.Root
                      value={values.clientId}
                      onChange={(e) => set("clientId", e.target.value)}
                      placeholder="mcp-gateway-client"
                      spellCheck={false}
                      className="font-mono"
                    />
                  </Field>
                  <Field label="Client secret" className="flex-1">
                    <TextField.Root
                      value={values.clientSecret}
                      onChange={(e) => set("clientSecret", e.target.value)}
                      type="password"
                      placeholder="••••••••••••"
                      className="font-mono"
                    />
                  </Field>
                </Flex>
              )}
            </div>
          )}
        </Flex>

        {(isAdmin || canManageAgentAccess) && (
          <>
            <SectionHeader label="Sharing" />
            <Text color="gray" className="text-[13px]">
              Once the server authenticates, you can configure tool approvals
              for each agent on the server page.
            </Text>
            <Flex direction="column" gap="3">
              {isAdmin && (
                <ToggleRow
                  title="Enabled for your organization"
                  description={
                    values.teamEnabled
                      ? "Anyone in your organization can find and use this server. Each person connects with their own account."
                      : "This server is turned off for everyone in your organization."
                  }
                  checked={values.teamEnabled}
                  onChange={(checked) => set("teamEnabled", checked)}
                />
              )}

              {canManageAgentAccess && (
                <div className="flex items-center justify-between gap-3 rounded-md border border-gray-5 bg-gray-2 p-3">
                  <div>
                    <div className="font-medium text-sm">
                      Who can use this connection?
                    </div>
                    <div className="text-[13px] text-gray-11">
                      {values.agentScope === "team"
                        ? "Anyone in this project can use this connection"
                        : "Only you can use this connection"}
                    </div>
                  </div>
                  <AgentScopeToggle
                    value={values.agentScope}
                    onChange={(agentScope) => set("agentScope", agentScope)}
                  />
                </div>
              )}
            </Flex>
          </>
        )}

        <Flex justify="end" gap="3" className="border-gray-5 border-t pt-4">
          <Button
            type="button"
            variant="soft"
            color="gray"
            onClick={() => onNavigate({ view: "servers" })}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={!canSave || registerPending}>
            {registerPending ? (
              <Spinner size="1" />
            ) : (
              <Check size={12} weight="bold" />
            )}{" "}
            Add server
          </Button>
        </Flex>
      </Flex>
    </form>
  );
}

function SectionHeader({ label }: { label: string }) {
  return <Text className="mt-2 font-medium text-base">{label}</Text>;
}

function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Flex direction="column" gap="1" className={className}>
      <Text className="font-medium text-sm">{label}</Text>
      {hint && (
        <Text color="gray" className="text-[13px]">
          {hint}
        </Text>
      )}
      {children}
    </Flex>
  );
}

function ToggleRow({
  title,
  description,
  checked,
  onChange,
}: {
  title: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      className="rounded-md border border-gray-5 bg-gray-2 p-3"
    >
      <div>
        <Text as="div" className="font-medium text-sm">
          {title}
        </Text>
        {description && (
          <Text as="div" color="gray" className="text-[13px]">
            {description}
          </Text>
        )}
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </Flex>
  );
}
