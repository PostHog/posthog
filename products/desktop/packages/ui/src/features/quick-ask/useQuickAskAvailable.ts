import { useServiceOptional } from "@posthog/di/react";
import {
  QUICK_ASK_SETTINGS_CLIENT,
  type QuickAskSettingsClient,
  type QuickAskState,
} from "@posthog/ui/features/quick-ask/identifiers";
import { useEffect, useState } from "react";

/**
 * True only when this host binds a quick-ask client and the build exposes the
 * panel. Web (client unbound) and packaged desktop without the prototype gate
 * both read false, so the settings page can hide itself instead of rendering a
 * dead end. Defaults to false until the async state resolves, so the entry
 * appears once availability is confirmed rather than flashing out.
 */
export function useQuickAskAvailable(): boolean {
  const client = useServiceOptional<QuickAskSettingsClient>(
    QUICK_ASK_SETTINGS_CLIENT,
  );
  const [state, setState] = useState<QuickAskState | null>(null);

  useEffect(() => {
    if (!client) return;
    let active = true;
    client.getState().then((next) => {
      if (active) setState(next);
    });
    return () => {
      active = false;
    };
  }, [client]);

  return !!client && !!state?.enabled;
}
