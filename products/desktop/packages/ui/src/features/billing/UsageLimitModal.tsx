import { Warning } from "@phosphor-icons/react";
import { formatResetTime } from "@posthog/core/billing/usageDisplay";
import type { UsageLimitContent } from "@posthog/core/billing/usageLimitContent";
import { usageLimitContent } from "@posthog/core/billing/usageLimitContent";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
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
    <AlertDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onDismiss();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <Warning size={18} weight="fill" color="var(--orange-9)" />
              {content.title}
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription>{content.description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          {content.actionLabel ? (
            <>
              <Button variant="outline" onClick={onDismiss}>
                {content.dismissLabel}
              </Button>
              <Button variant="primary" onClick={onAction}>
                {content.actionLabel}
              </Button>
            </>
          ) : (
            <Button variant="primary" onClick={onDismiss}>
              {content.dismissLabel}
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
