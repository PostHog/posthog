import { createContext, type ReactNode, useContext } from "react";

export const PRIVATE_SPACE_MENTIONS_DISABLED =
  "Mentions aren’t available in your personal space.";

const MentionAvailabilityContext = createContext<string | null>(null);

export function MentionAvailabilityProvider({
  disabledReason,
  children,
}: {
  disabledReason: string | null;
  children: ReactNode;
}) {
  return (
    <MentionAvailabilityContext.Provider value={disabledReason}>
      {children}
    </MentionAvailabilityContext.Provider>
  );
}

export function useMentionsDisabledReason(): string | null {
  return useContext(MentionAvailabilityContext);
}
