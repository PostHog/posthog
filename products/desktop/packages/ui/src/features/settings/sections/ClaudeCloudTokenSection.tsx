import { Button, Input, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { setCloudSubscriptionOn } from "@posthog/ui/features/settings/adapterSubscription";
import {
  useClaudeCloudAccount,
  useConnectClaudeCloudAccount,
  useDisconnectClaudeCloudAccount,
  useLocalClaudeToken,
} from "@posthog/ui/features/settings/claudeCloudAccount";
import { isValidClaudeSetupToken } from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { type ReactElement, useId, useState } from "react";

interface ClaudeCloudTokenSectionProps {
  cloudSubscriptionOn: boolean;
  onCreateToken: () => void;
}

export function ClaudeCloudTokenSection({
  cloudSubscriptionOn,
  onCreateToken,
}: ClaudeCloudTokenSectionProps): ReactElement | null {
  const account = useClaudeCloudAccount();
  const { tokenStore, query: localToken } = useLocalClaudeToken();
  const connect = useConnectClaudeCloudAccount(tokenStore);
  const disconnect = useDisconnectClaudeCloudAccount(tokenStore);
  const [tokenDraft, setTokenDraft] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const validationErrorId = useId();
  const [confirmRemoval, setConfirmRemoval] = useState(false);
  const [replacingToken, setReplacingToken] = useState(false);

  if (!tokenStore) return null;

  const pending = connect.isPending || disconnect.isPending;
  const hasLocalToken = localToken.data === true;
  const serverStoresToken = account.data !== null;
  const status = serverStoresToken
    ? (account.data?.status ?? "not_connected")
    : hasLocalToken
      ? "connected"
      : "not_connected";

  const saveToken = (): void => {
    if (pending) return;
    const token = tokenDraft.trim();
    if (!isValidClaudeSetupToken(token)) {
      setValidationError(
        "Paste the full token from the terminal. It starts with sk-ant-oat01-.",
      );
      return;
    }
    setValidationError(null);
    connect.mutate(token, {
      onSuccess: ({ localSaveError }) => {
        setTokenDraft("");
        setReplacingToken(false);
        track(ANALYTICS_EVENTS.CLAUDE_CLOUD_TOKEN_SAVED);
        if (localSaveError) {
          toast.warning("Token saved", {
            description: `Desktop could not keep a copy on this device, so resumed older tasks can fail. ${localSaveError.message}`,
          });
        } else {
          toast.success("Token saved");
        }
      },
      onError: (error) =>
        toast.error("Cannot save the token.", { description: error.message }),
    });
  };

  const removeToken = (): void => {
    if (pending) return;
    disconnect.mutate(undefined, {
      onSuccess: () => {
        setConfirmRemoval(false);
        track(ANALYTICS_EVENTS.CLAUDE_CLOUD_TOKEN_REMOVED);
        toast.success("Token removed");
      },
      onError: () => toast.error("Cannot remove the token. Try again."),
    });
  };

  const removalRow = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-muted-foreground text-xs">
        Remove the saved token?
      </span>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={pending}
          onClick={() => setConfirmRemoval(false)}
        >
          Cancel
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={pending}
          loading={disconnect.isPending}
          data-attr="claude-cloud-token-remove"
          onClick={removeToken}
        >
          Confirm removal
        </Button>
      </div>
    </div>
  );

  const formHint =
    status === "reauth_required"
      ? "Your Claude token stopped working. Create a new token, then paste it below."
      : hasLocalToken && serverStoresToken
        ? "Paste your token again so cloud tasks can run when Desktop is closed."
        : "Create a token, then paste it below.";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-xs">Cloud tasks</span>
        <Switch
          size="sm"
          aria-label="Use your Claude plan for cloud tasks"
          data-attr="claude-cloud-subscription-toggle"
          checked={cloudSubscriptionOn}
          disabled={pending}
          onCheckedChange={(checked) => {
            const next = checked === true;
            if (next === cloudSubscriptionOn) return;
            setCloudSubscriptionOn("claude", next);
          }}
        />
      </div>
      {account.isSuccess ? (
        <span className="text-muted-foreground text-xs">
          {!serverStoresToken
            ? "Keep Desktop open to start or resume. Compute is billed separately."
            : status === "connected"
              ? "PostHog keeps your Claude token for your cloud tasks. Tasks run when Desktop is closed. Compute is billed separately."
              : "Save a token so cloud tasks can run when Desktop is closed. Compute is billed separately."}
        </span>
      ) : null}
      {account.isPending || (!serverStoresToken && localToken.isPending) ? (
        <output className="text-muted-foreground text-xs">
          Checking token…
        </output>
      ) : account.isError ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span role="alert" className="text-muted-foreground text-xs">
            Cannot check your Claude token. {account.error.message}
          </span>
          <Button
            size="sm"
            variant="outline"
            loading={account.isFetching}
            onClick={() => void account.refetch()}
          >
            Try again
          </Button>
        </div>
      ) : status === "connected" && !replacingToken ? (
        confirmRemoval ? (
          removalRow
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-muted-foreground text-xs">
              <span
                className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-(--green-9)"
                aria-hidden
              />
              Token saved
            </span>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={pending}
                onClick={() => setReplacingToken(true)}
                data-attr="claude-cloud-token-replace"
              >
                Replace token
              </Button>
              <Button
                type="button"
                variant="link-muted"
                size="sm"
                disabled={pending}
                onClick={() => setConfirmRemoval(true)}
              >
                Remove token
              </Button>
            </div>
          </div>
        )
      ) : (
        <div className="flex flex-col gap-3 rounded-md border border-border p-3">
          {confirmRemoval ? (
            removalRow
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span
                role={status === "reauth_required" ? "alert" : undefined}
                className="text-muted-foreground text-xs"
              >
                {formHint}
              </span>
              <div className="flex items-center gap-2">
                {hasLocalToken && !replacingToken ? (
                  <Button
                    type="button"
                    variant="link-muted"
                    size="sm"
                    disabled={pending}
                    onClick={() => setConfirmRemoval(true)}
                  >
                    Remove token
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onCreateToken}
                  disabled={pending}
                >
                  Create token
                </Button>
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="password"
              autoComplete="off"
              placeholder="Paste your Claude token"
              aria-label="Claude setup token"
              aria-invalid={validationError ? true : undefined}
              aria-describedby={validationError ? validationErrorId : undefined}
              data-attr="claude-cloud-subscription-token"
              className="h-7 min-w-40 flex-1 text-xs"
              value={tokenDraft}
              onChange={(event) => {
                setTokenDraft(event.currentTarget.value.replace(/\s/g, ""));
                setValidationError(null);
              }}
              disabled={pending}
            />
            <Button
              type="button"
              variant="primary"
              size="sm"
              data-attr="claude-cloud-token-save"
              onClick={saveToken}
              disabled={!tokenDraft.trim() || pending}
              loading={connect.isPending}
            >
              Save token
            </Button>
            {replacingToken ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={pending}
                onClick={() => {
                  setTokenDraft("");
                  setValidationError(null);
                  setReplacingToken(false);
                }}
              >
                Cancel
              </Button>
            ) : null}
          </div>
          {validationError ? (
            <span
              id={validationErrorId}
              role="alert"
              className="text-(--red-11) text-xs"
            >
              {validationError}
            </span>
          ) : null}
          <span className="text-muted-foreground text-xs">
            PostHog stores this token. It is used only for your cloud tasks.
          </span>
        </div>
      )}
    </div>
  );
}
