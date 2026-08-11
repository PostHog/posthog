import { CaretRight, Key } from "@phosphor-icons/react";
import type { McpAuthType } from "@posthog/api-client/posthog-client";
import {
  canSubmitGatewayConnect,
  GATEWAY_CONNECT_DEFAULTS,
  type GatewayConnectCredentials,
} from "@posthog/core/mcp-gateway/gatewayConnect";
import {
  Button,
  Dialog,
  Flex,
  Select,
  Text,
  TextField,
} from "@radix-ui/themes";
import { type FormEvent, useState } from "react";

interface GatewayConnectDialogProps {
  open: boolean;
  serverName: string;
  /**
   * Auth mechanism fixed by the catalog template, or null for custom servers
   * where the member chooses their own.
   */
  fixedAuthType: McpAuthType | null;
  onSubmit: (credentials: GatewayConnectCredentials) => void;
  onClose: () => void;
}

/**
 * Collects the caller's personal credentials before connecting: the API key
 * for api-key servers, and — for custom servers, which have no fixed auth
 * mechanism — the choice between OAuth and API key. Plain OAuth templates
 * never open this; they go straight to the browser round-trip.
 */
export function GatewayConnectDialog({
  open,
  serverName,
  fixedAuthType,
  onSubmit,
  onClose,
}: GatewayConnectDialogProps) {
  const [values, setValues] = useState<GatewayConnectCredentials>({
    ...GATEWAY_CONNECT_DEFAULTS,
    authType: fixedAuthType ?? "oauth",
  });
  const [showKey, setShowKey] = useState(false);
  const [optionalOpen, setOptionalOpen] = useState(false);

  const set = <K extends keyof GatewayConnectCredentials>(
    key: K,
    value: GatewayConnectCredentials[K],
  ) => setValues((previous) => ({ ...previous, [key]: value }));

  const memberChooses = fixedAuthType === null;
  const canSubmit = canSubmitGatewayConnect(values);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit(values);
  };

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Content maxWidth="480px">
        <Dialog.Title>Connect {serverName}</Dialog.Title>
        <Dialog.Description color="gray" className="text-sm">
          {memberChooses
            ? "Choose how this server authenticates, then enter your personal credentials."
            : "Enter the credentials for your personal connection."}
        </Dialog.Description>
        <form onSubmit={submit}>
          <Flex direction="column" gap="3" mt="4">
            {memberChooses && (
              <Field label="Authentication">
                <Select.Root
                  value={values.authType}
                  onValueChange={(value) =>
                    set("authType", value as McpAuthType)
                  }
                >
                  <Select.Trigger />
                  <Select.Content>
                    <Select.Item value="oauth">
                      OAuth — sign in with the provider
                    </Select.Item>
                    <Select.Item value="api_key">API key</Select.Item>
                  </Select.Content>
                </Select.Root>
              </Field>
            )}

            {values.authType === "api_key" ? (
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
                  autoFocus
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
            ) : (
              memberChooses && (
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
                      Client ID &amp; secret — only if the provider doesn't
                      support dynamic client registration
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
              )
            )}

            <Flex justify="end" gap="3" mt="2">
              <Button
                type="button"
                variant="soft"
                color="gray"
                onClick={onClose}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={!canSubmit}>
                <Key size={12} /> Connect
              </Button>
            </Flex>
          </Flex>
        </form>
      </Dialog.Content>
    </Dialog.Root>
  );
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
