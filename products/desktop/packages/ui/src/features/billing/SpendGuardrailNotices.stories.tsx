import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect } from "react";
import { toast } from "../../primitives/toast";

/**
 * The two inform-only notices the spend guardrails raise, fired through the
 * real toast pipeline so copy and styling review the same way they ship.
 */
function SpendGuardrailNotices({
  level,
}: {
  level: "warn" | "alert" | "both";
}) {
  useEffect(() => {
    const action = { label: "View spend", onClick: () => {} };
    if (level !== "alert") {
      toast.warning("Daily spend passed $20.00", {
        id: "story-spend-warn",
        description: "$21.37 spent in this app today. Nothing is paused.",
        action,
        duration: Number.POSITIVE_INFINITY,
      });
    }
    if (level !== "warn") {
      toast.warning("Monthly spend passed your $200.00 alert line", {
        id: "story-spend-alert",
        description: "$204.10 spent in this app this month. Nothing is paused.",
        action,
        duration: Number.POSITIVE_INFINITY,
      });
    }
  }, [level]);
  return (
    <div className="p-6 text-(--gray-11) text-sm">
      Spend notices render as toasts in the corner.
    </div>
  );
}

const meta: Meta<typeof SpendGuardrailNotices> = {
  title: "Billing/Spend guardrail notices",
  component: SpendGuardrailNotices,
};

export default meta;
type Story = StoryObj<typeof SpendGuardrailNotices>;

export const WarningNotice: Story = { args: { level: "warn" } };
export const AlertNotice: Story = { args: { level: "alert" } };
export const BothNotices: Story = { args: { level: "both" } };
