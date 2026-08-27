import { Warning } from "@phosphor-icons/react";
import { formatResetTime } from "@posthog/core/billing/usageDisplay";
import type { UsageLimitContent } from "@posthog/core/billing/usageLimitContent";
import { usageLimitContent } from "@posthog/core/billing/usageLimitContent";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { AlertDialog, Button, Flex } from "@radix-ui/themes";
import { useEffect } from "react";
import { track } from "../../shell/analytics";
import { openExternalUrl } from "../../shell/openExternal";
import { getBillingUrl } from "../../utils/urls";
import { useAuthStateValue } from "../auth/store";
import { useIsOrgAdmin } from "../auth/useOrgRole";
import { useUsageLimitStore } from "./usageLimitStore";
import { useUsage } from "./useUsage";

export function UsageLimitModal() {
  const isOpen = useUsageLimitStore((s) => s.isOpen);
  const resetAt = useUsageLimitStore((s) => s.resetAt);
  const cause = useUsageLimitStore((s) => s.cause);
  const hide = useUsageLimitStore((s) => s.hide);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const { isAdmin } = useIsOrgAdmin();
  const { usage } = useUsage({ enabled: isOpen });

  useEffect(() => {
    if (isOpen) {
      track(ANALYTICS_EVENTS.UPGRADE_PROMPT_SHOWN, {
        surface: "usage_limit_modal",
        ...(cause ? { cause } : {}),
      });
    }
  }, [isOpen, cause]);

  const content = usageLimitContent({
    cause,
    resetLabel: resetAt ? formatResetTime(resetAt) : null,
    subscribed: usage?.code_usage_subscribed,
    canManageBilling: isAdmin === true,
  });

  const handleAction = () => {
    track(ANALYTICS_EVENTS.UPGRADE_PROMPT_CLICKED, {
      surface: "usage_limit_modal",
      ...(cause ? { cause } : {}),
    });
    hide();
    const billingUrl = getBillingUrl(cloudRegion);
    if (billingUrl) openExternalUrl(billingUrl);
  };

  return (
    <UsageLimitModalContent
      open={isOpen}
      content={content}
      onDismiss={hide}
      onAction={handleAction}
    />
  );
}

export function UsageLimitModalContent({
  open,
  content,
  onDismiss,
  onAction,
}: {
  open: boolean;
  content: UsageLimitContent;
  onDismiss: () => void;
  onAction: () => void;
}) {
  return (
    <AlertDialog.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onDismiss();
      }}
    >
      <AlertDialog.Content maxWidth="420px" size="2">
        <AlertDialog.Title className="text-base">
          <Flex align="center" gap="2">
            <Warning size={18} weight="fill" color="var(--orange-9)" />
            {content.title}
          </Flex>
        </AlertDialog.Title>
        <AlertDialog.Description className="text-sm">
          {content.description}
        </AlertDialog.Description>

        <Flex justify="end" gap="2" mt="4">
          <AlertDialog.Cancel>
            {content.actionLabel ? (
              <Button variant="soft" color="gray" size="1">
                {content.dismissLabel}
              </Button>
            ) : (
              <Button variant="solid" size="1">
                {content.dismissLabel}
              </Button>
            )}
          </AlertDialog.Cancel>
          {content.actionLabel && (
            <AlertDialog.Action>
              <Button variant="solid" size="1" onClick={onAction}>
                {content.actionLabel}
              </Button>
            </AlertDialog.Action>
          )}
        </Flex>
      </AlertDialog.Content>
    </AlertDialog.Root>
  );
}
