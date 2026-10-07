import { Button } from "@posthog/quill";
import { useState } from "react";
import { useSettingsStore } from "./settingsStore";

export function SettingsRecovery(): React.JSX.Element | null {
  const hydrated = useSettingsStore((state) => state._hasHydrated);
  const failed = useSettingsStore((state) => state._hydrationError);
  const [retrying, setRetrying] = useState(false);
  if (hydrated && !failed) return null;
  return (
    <output className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3 text-xs">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="font-medium">
          {failed ? "Billing choice unavailable" : "Loading billing choice…"}
        </span>
        {failed && (
          <span className="text-muted-foreground">
            We could not read your saved settings. Your saved data has not
            changed. New cloud tasks cannot start until your settings load.
          </span>
        )}
      </div>
      {failed && (
        <Button
          size="sm"
          variant="outline"
          loading={retrying}
          disabled={retrying}
          onClick={async () => {
            if (retrying) return;
            setRetrying(true);
            try {
              await useSettingsStore.persist.rehydrate();
            } finally {
              setRetrying(false);
            }
          }}
        >
          Try again
        </Button>
      )}
    </output>
  );
}
