import { AnswerCard } from "@posthog/quick-ask/panel/components/AnswerCard";
import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import { ReportReferenceNavigationContext } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { ThemeWrapper } from "@posthog/ui/primitives/ThemeWrapper";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/quill-charts", () => ({
  BarChart: () => null,
  LineChart: () => null,
  TimeSeriesBarChart: () => null,
  TimeSeriesLineChart: () => null,
  useChartTheme: () => ({}),
}));
vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));
vi.mock("@posthog/ui/features/editor/useEvidencePreviewPrefetch", () => ({
  useEvidencePreviewPrefetch: () => {},
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({ isPending: true }),
}));

afterEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ authState: ANONYMOUS_AUTH_STATE });
});

describe("Quick Ask report navigation", () => {
  it.each([
    { kind: "report", signedIn: true },
    { kind: "report", signedIn: false },
    { kind: "insight", signedIn: true },
  ] as const)(
    "handles a $kind click with signedIn=$signedIn",
    async ({ kind, signedIn }) => {
      useAuthStore.setState({
        authState: signedIn
          ? { ...ANONYMOUS_AUTH_STATE, cloudRegion: "us", currentProjectId: 2 }
          : ANONYMOUS_AUTH_STATE,
      });
      const openReport = vi.fn().mockResolvedValue(undefined);
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const { unmount } = render(
        <QueryClientProvider client={queryClient}>
          <ThemeWrapper>
            <ReportReferenceNavigationContext.Provider value={openReport}>
              <AnswerCard
                parts={[
                  {
                    id: "answer-1",
                    content: `Open <${kind} id="reference-1">Linked reference</${kind}>.`,
                    complete: true,
                  },
                ]}
                streaming={false}
                statusLabel={null}
                onOpenInApp={vi.fn()}
              />
            </ReportReferenceNavigationContext.Provider>
          </ThemeWrapper>
        </QueryClientProvider>,
      );

      await act(async () => {
        fireEvent.click(screen.getByRole("link", { name: "Linked reference" }));
      });

      if (kind === "report") {
        expect(openReport).toHaveBeenCalledExactlyOnceWith("reference-1");
      } else {
        expect(openReport).not.toHaveBeenCalled();
      }
      expect(openExternalUrl).not.toHaveBeenCalled();
      unmount();
      queryClient.clear();
    },
  );
});
