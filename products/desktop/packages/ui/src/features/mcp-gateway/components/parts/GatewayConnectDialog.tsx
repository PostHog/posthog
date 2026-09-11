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
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldDescription,
  FieldLabel,
  Input,
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Text,
} from "@posthog/quill";
import { type FormEvent, useState } from "react";

interface GatewayConnectDialogProps {
  open: boolean;
  serverName: string;
  /**
   * Auth mechanism fixed by the catalog template, or null for custom servers
   * where the member chooses their own.
   */
  fixedAuthType: McpAuthType | null;
  /** Custom servers may need a member-supplied OAuth client. */
  isCustomServer?: boolean;
  onSubmit: (credentials: GatewayConnectCredentials) => void;
  onClose: () => void;
}

/**
 * Collects the caller's personal credentials before connecting: the API key
 * for api-key servers, the optional OAuth client for custom OAuth servers,
 * and — for custom servers with no recorded auth mechanism — the choice
 * between OAuth and API key. Plain OAuth templates never open this; they go
 * straight to the browser round-trip.
 */
export function GatewayConnectDialog({
  open,
  serverName,
  fixedAuthType,
  isCustomServer = false,
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
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Connect {serverName}</DialogTitle>
          <DialogDescription>
            {memberChooses
              ? "Choose how this server authenticates, then enter your personal credentials."
              : values.authType === "api_key"
                ? "This server uses an API key. Enter your own key to connect."
                : "Enter the credentials for your personal connection."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="contents">
          <DialogBody viewportClassName="flex flex-col gap-3">
            {memberChooses && (
              <Field>
                <FieldLabel htmlFor="gateway-authentication">
                  Authentication
                </FieldLabel>
                <Select
                  value={values.authType}
                  onValueChange={(value) =>
                    set("authType", value as McpAuthType)
                  }
                >
                  <SelectTrigger id="gateway-authentication" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="oauth">
                      OAuth — sign in with the provider
                    </SelectItem>
                    <SelectItem value="api_key">API key</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            )}

            {values.authType === "api_key" ? (
              <Field>
                <FieldLabel htmlFor="gateway-api-key">API key</FieldLabel>
                <FieldDescription>
                  Encrypted at rest and never logged or exposed.
                </FieldDescription>
                <InputGroup>
                  <InputGroupInput
                    id="gateway-api-key"
                    value={values.apiKey}
                    onChange={(event) => set("apiKey", event.target.value)}
                    type={showKey ? "text" : "password"}
                    placeholder="Enter API key"
                    spellCheck={false}
                    autoFocus
                    className="font-mono"
                  />
                  <InputGroupAddon align="inline-end">
                    <InputGroupButton
                      type="button"
                      onClick={() => setShowKey((value) => !value)}
                    >
                      {showKey ? "Hide" : "Show"}
                    </InputGroupButton>
                  </InputGroupAddon>
                </InputGroup>
              </Field>
            ) : (
              isCustomServer && (
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
                    <Text render={<span />} size="sm" weight="medium">
                      Optional
                    </Text>
                    <Text render={<span />} size="xs" variant="muted">
                      Client ID &amp; secret — only if the provider doesn't
                      support dynamic client registration
                    </Text>
                  </button>
                  {optionalOpen && (
                    <div className="flex gap-3 px-3 pb-3">
                      <Field className="flex-1">
                        <FieldLabel htmlFor="gateway-client-id">
                          Client ID
                        </FieldLabel>
                        <Input
                          id="gateway-client-id"
                          value={values.clientId}
                          onChange={(event) =>
                            set("clientId", event.target.value)
                          }
                          placeholder="mcp-gateway-client"
                          spellCheck={false}
                          className="font-mono"
                        />
                      </Field>
                      <Field className="flex-1">
                        <FieldLabel htmlFor="gateway-client-secret">
                          Client secret
                        </FieldLabel>
                        <Input
                          id="gateway-client-secret"
                          value={values.clientSecret}
                          onChange={(event) =>
                            set("clientSecret", event.target.value)
                          }
                          type="password"
                          placeholder="••••••••••••"
                          className="font-mono"
                        />
                      </Field>
                    </div>
                  )}
                </div>
              )
            )}
          </DialogBody>
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              Cancel
            </DialogClose>
            <Button type="submit" variant="primary" disabled={!canSubmit}>
              <Key /> Connect
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
