import { WarningCircle } from "@phosphor-icons/react";
import { formatResetTime } from "@posthog/core/billing/usageDisplay";
import { usageLimitContent } from "@posthog/core/billing/usageLimitContent";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { Button, Dialog, Flex, Text } from "@radix-ui/themes";
import { useEffect } from "react";
import { track } from "../../shell/analytics";
import { openExternalUrl } from "../../shell/openExternal";
import { getBillingUrl } from "../../utils/urls";
import { useAuthStateValue } from "../auth/store";
import { useUsageLimitStore } from "./usageLimitStore";
import { useUsage } from "./useUsage";

export function UsageLimitModal() {
  const isOpen = useUsageLimitStore((s) => s.isOpen);
  const resetAt = useUsageLimitStore((s) => s.resetAt);
  const cause = useUsageLimitStore((s) => s.cause);
  const hide = useUsageLimitStore((s) => s.hide);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
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
    <Dialog.Root open={isOpen}>
      <Dialog.Content
        maxWidth="400px"
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={hide}
      >
        <Flex direction="column" gap="3">
          <Flex align="center" gap="2">
            <WarningCircle size={20} weight="bold" color="var(--red-9)" />
            <Dialog.Title className="mb-0">{content.title}</Dialog.Title>
          </Flex>
          <Dialog.Description>
            <Text color="gray" className="text-sm">
              {content.description}
            </Text>
          </Dialog.Description>
          <Flex justify="end" gap="3" mt="2">
            <Button
              type="button"
              {...(content.actionLabel
                ? { variant: "soft" as const, color: "gray" as const }
                : {})}
              onClick={hide}
            >
              {content.dismissLabel}
            </Button>
            {content.actionLabel && (
              <Button type="button" onClick={handleAction}>
                {content.actionLabel}
              </Button>
            )}
          </Flex>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
