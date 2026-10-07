import type { ModelAccess } from "@posthog/shared";
import { SettingsRecovery } from "./SettingsRecovery";
import { useSettingsStore } from "./settingsStore";

export function CloudBillingSummary({
  modelAccess,
}: {
  modelAccess?: ModelAccess;
}): React.JSX.Element {
  const ready = useSettingsStore(
    (state) => state._hasHydrated && !state._hydrationError,
  );
  if (!ready) return <SettingsRecovery />;
  return (
    <p
      className="px-2 py-1 text-muted-foreground text-xs"
      data-attr="cloud-billing-summary"
    >
      Models:{" "}
      {modelAccess === "own-subscription"
        ? "your subscription"
        : "PostHog credits"}{" "}
      · Compute: PostHog credits
    </p>
  );
}
