import { useServiceOptional } from "@posthog/di/react";
import { Button, Input, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { setClaudeCloudSubscriptionOn as setCloudSubscriptionOn } from "@posthog/ui/features/settings/adapterSubscription";
import {
  CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
  type ClaudeSubscriptionTokenSettings,
  claudeSubscriptionTokenQueryKey,
  isValidClaudeSetupToken,
} from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useId, useState } from "react";

interface ClaudeCloudTokenSectionProps {
  cloudSubscriptionOn: boolean;
  onCreateToken: () => void;
}

export function ClaudeCloudTokenSection({
  cloudSubscriptionOn,
  onCreateToken,
}: ClaudeCloudTokenSectionProps): ReactElement | null {
  const tokenStore = useServiceOptional<ClaudeSubscriptionTokenSettings>(
    CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
  );
  const queryClient = useQueryClient();
  const tokenQuery = useQuery({
    queryKey: claudeSubscriptionTokenQueryKey,
    queryFn: () => tokenStore?.has() ?? Promise.resolve(false),
    enabled: !!tokenStore,
    retry: false,
  });
  const [tokenDraft, setTokenDraft] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const validationErrorId = useId();
  const [pendingAction, setPendingAction] = useState<"save" | "remove" | null>(
    null,
  );
  const [confirmRemoval, setConfirmRemoval] = useState(false);
  const [replacingToken, setReplacingToken] = useState(false);

  if (!tokenStore) return null;

  const saveToken = async (): Promise<void> => {
    if (pendingAction) return;
    const token = tokenDraft.trim();
    if (!isValidClaudeSetupToken(token)) {
      setValidationError(
        "Paste the full token from the terminal. It starts with sk-ant-oat01-.",
      );
      return;
    }
    setValidationError(null);
    setPendingAction("save");
    try {
      await tokenStore.save(token);
      setTokenDraft("");
      setReplacingToken(false);
      queryClient.setQueryData(claudeSubscriptionTokenQueryKey, true);
      track(ANALYTICS_EVENTS.CLAUDE_CLOUD_TOKEN_SAVED);
      toast.success("Token saved");
    } catch (error) {
      toast.error("Cannot save the token.", {
        description:
          error instanceof Error
            ? error.message
            : "Check your system key store and try again.",
      });
    } finally {
      setPendingAction(null);
    }
  };

  const removeToken = async (): Promise<void> => {
    if (pendingAction) return;
    setPendingAction("remove");
    try {
      await tokenStore.clear();
      queryClient.setQueryData(claudeSubscriptionTokenQueryKey, false);
      setConfirmRemoval(false);
      track(ANALYTICS_EVENTS.CLAUDE_CLOUD_TOKEN_REMOVED);
      toast.success("Token removed");
    } catch {
      toast.error("Cannot remove the token. Try again.");
    } finally {
      setPendingAction(null);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-xs">Cloud tasks</span>
        <Switch
          size="sm"
          aria-label="Use your Claude plan for cloud tasks"
          data-attr="claude-cloud-subscription-toggle"
          checked={cloudSubscriptionOn}
          disabled={!!pendingAction}
          onCheckedChange={(checked) => {
            const next = checked === true;
            if (next === cloudSubscriptionOn) return;
            setCloudSubscriptionOn(next);
          }}
        />
      </div>
      <span className="text-muted-foreground text-xs">
        Keep Desktop open to start or resume. Compute is billed separately.
      </span>
      {tokenQuery.isPending ? (
        <output className="text-muted-foreground text-xs">
          Checking token…
        </output>
      ) : (tokenQuery.data || tokenQuery.isError) && !replacingToken ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span
            role={tokenQuery.isError ? "alert" : undefined}
            className="text-muted-foreground text-xs"
          >
            {confirmRemoval
              ? "Remove the saved token?"
              : tokenQuery.isError
                ? tokenQuery.error.message
                : "Token saved"}
          </span>
          {confirmRemoval ? (
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!!pendingAction}
                onClick={() => setConfirmRemoval(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!!pendingAction}
                loading={pendingAction === "remove"}
                data-attr="claude-cloud-token-remove"
                onClick={() => void removeToken()}
              >
                Confirm removal
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              {tokenQuery.isError ? (
                <Button
                  size="sm"
                  variant="outline"
                  loading={tokenQuery.isFetching}
                  onClick={() => void tokenQuery.refetch()}
                >
                  Try again
                </Button>
              ) : null}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setReplacingToken(true)}
                data-attr="claude-cloud-token-replace"
              >
                Replace token
              </Button>
              <Button
                type="button"
                variant="link-muted"
                size="sm"
                onClick={() => setConfirmRemoval(true)}
              >
                Remove token
              </Button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3 rounded-md border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-muted-foreground text-xs">
              Create a token, then paste it below.
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onCreateToken}
              disabled={!!pendingAction}
            >
              Create token
            </Button>
          </div>
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
              disabled={!!pendingAction}
            />
            <Button
              type="button"
              variant="primary"
              size="sm"
              data-attr="claude-cloud-token-save"
              onClick={() => void saveToken()}
              disabled={!tokenDraft.trim() || !!pendingAction}
              loading={pendingAction === "save"}
            >
              Save token
            </Button>
            {replacingToken ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!!pendingAction}
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
            Protected by your system key store. Used only for your cloud tasks.
          </span>
        </div>
      )}
    </div>
  );
}
