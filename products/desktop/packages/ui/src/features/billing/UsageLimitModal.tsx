import { WarningCircle } from "@phosphor-icons/react";
import { formatResetTime } from "@posthog/core/billing/usageDisplay";
import type { UsageLimitContent } from "@posthog/core/billing/usageLimitContent";
import { usageLimitContent } from "@posthog/core/billing/usageLimitContent";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
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
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onDismiss()}>
      <DialogContent className="sm:max-w-[400px]">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <WarningCircle size={20} weight="bold" color="var(--red-9)" />
            <DialogTitle className="mb-0">{content.title}</DialogTitle>
          </div>
          <DialogDescription className="text-(--gray-11) text-sm">
            {content.description}
          </DialogDescription>
          <DialogFooter className="border-t-0 bg-transparent">
            <Button
              type="button"
              variant={content.actionLabel ? "outline" : "primary"}
              onClick={onDismiss}
            >
              {content.dismissLabel}
            </Button>
            {content.actionLabel && (
              <Button type="button" onClick={onAction}>
                {content.actionLabel}
              </Button>
            )}
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
