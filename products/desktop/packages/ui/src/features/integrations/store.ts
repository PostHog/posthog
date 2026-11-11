import {
  classifyIntegrations,
  type Integration,
} from "@posthog/core/integrations/selectors";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { create } from "zustand";

export type { Integration } from "@posthog/core/integrations/selectors";

interface IntegrationStore {
  integrations: Integration[];
  scope: string | null;
  setIntegrations: (integrations: Integration[], scope: string | null) => void;
}

export const useIntegrationStore = create<IntegrationStore>((set) => ({
  integrations: [],
  scope: null,
  setIntegrations: (integrations, scope) => set({ integrations, scope }),
}));

export const useIntegrationSelectors = () => {
  const scope = useAuthStateValue(getAuthIdentity);
  const state = useIntegrationStore();
  return classifyIntegrations(
    scope !== null && state.scope === scope ? state.integrations : [],
  );
};
