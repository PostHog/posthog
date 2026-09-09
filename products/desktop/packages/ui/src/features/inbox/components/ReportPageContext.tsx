import type { SignalReport } from "@posthog/shared/types";
import { createContext, useContext } from "react";

export const ReportPageContext = createContext<SignalReport | null>(null);

export function useReportPage() {
  return useContext(ReportPageContext);
}
