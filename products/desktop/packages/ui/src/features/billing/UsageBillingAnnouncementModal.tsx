import { ArrowSquareOut, CreditCard } from "@phosphor-icons/react";
import {
  codeOrgSpendLimitUsd,
  formatUsdAmount,
} from "@posthog/core/billing/usageDisplay";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { Button, Dialog, Flex, Text } from "@radix-ui/themes";
import { useEffect } from "react";
import { track } from "../../shell/analytics";
import { openExternalUrl } from "../../shell/openExternal";
import { getBillingUrl } from "../../utils/urls";
import { useAuthStateValue } from "../auth/store";
import { useBillingAnnouncementStore } from "./billingAnnouncementStore";
import { useBillingAnnouncementVisible } from "./useBillingAnnouncementVisible";
import { useUsage } from "./useUsage";

/**
 * One-time blocking announcement of the usage-based billing cutover. The
 * flag is its launch switch — flip at cutover, delete once the fleet has
 * acknowledged.
 */
export function UsageBillingAnnouncementModal() {
  const isOpen = useBillingAnnouncementVisible();
  const acknowledge = useBillingAnnouncementStore((s) => s.acknowledge);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const { usage } = useUsage({ enabled: isOpen });

  const spendLimitUsd = codeOrgSpendLimitUsd(usage);

  useEffect(() => {
    if (isOpen) {
      track(ANALYTICS_EVENTS.UPGRADE_PROMPT_SHOWN, {
        surface: "billing_announcement",
      });
    }
  }, [isOpen]);

  const handleAcknowledge = () => {
    track(ANALYTICS_EVENTS.USAGE_BILLING_ANNOUNCEMENT_ACKNOWLEDGED, {
      $set: {
        code_usage_billing_acknowledged_at: new Date().toISOString(),
      },
    });
    acknowledge();
  };

  const handleManageBilling = () => {
    track(ANALYTICS_EVENTS.UPGRADE_PROMPT_CLICKED, {
      surface: "billing_announcement",
    });
    const billingUrl = getBillingUrl(cloudRegion);
    if (billingUrl) openExternalUrl(billingUrl);
  };

  return (
    <Dialog.Root open={isOpen}>
      <Dialog.Content
        maxWidth="480px"
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
      >
        <Flex direction="column" gap="3">
          <Flex align="center" gap="2">
            <CreditCard size={20} weight="bold" color="var(--accent-9)" />
            <Dialog.Title className="mb-0">Billing has changed</Dialog.Title>
          </Flex>
          <Dialog.Description>
            <Text className="text-sm">
              Seat-based plans are gone — usage-based billing is here. You only
              pay for what you use.
            </Text>
          </Dialog.Description>
          <Flex direction="column" gap="2" className="text-sm">
            <Text color="gray">
              • The first <Text weight="medium">$20</Text> of usage each month
              is included.
            </Text>
            <Text color="gray">
              • Premium models need a payment method; an open model stays free.
            </Text>
            <Text color="gray">
              {spendLimitUsd != null ? (
                <>
                  • Your organization's spend limit is{" "}
                  <Text weight="medium">{`${formatUsdAmount(spendLimitUsd)}/month`}</Text>{" "}
                  — adjust it any time in billing settings.
                </>
              ) : (
                <>
                  • A default <Text weight="medium">$50/month</Text> spend limit
                  applies — adjust it any time in billing settings.
                </>
              )}
            </Text>
          </Flex>
          <Flex justify="end" gap="3" mt="2">
            <Button
              type="button"
              variant="soft"
              color="gray"
              onClick={handleManageBilling}
            >
              Manage billing
              <ArrowSquareOut size={12} />
            </Button>
            <Button type="button" onClick={handleAcknowledge}>
              Got it
            </Button>
          </Flex>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
