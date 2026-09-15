import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ triageEnabled: true, pathname: "/inbox" }));

vi.mock("@posthog/ui/features/feature-flags/useTriageFocusEnabled", () => ({
  useTriageFocusEnabled: () => mocks.triageEnabled,
}));

vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children, ...rest }: { to: string; children?: ReactNode }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
  useRouterState: ({ select }: { select: (state: unknown) => unknown }) =>
    select({ location: { pathname: mocks.pathname } }),
}));

import { InboxTriageButton } from "./InboxTriageButton";

describe("InboxTriageButton", () => {
  beforeEach(() => {
    mocks.triageEnabled = true;
    mocks.pathname = "/inbox";
  });

  it("stays in the header when nothing needs a decision", () => {
    render(<InboxTriageButton triageReportCount={0} />);

    expect(screen.getByRole("button", { name: "Triage mode" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("links to the triage queue when reports need a decision", () => {
    render(<InboxTriageButton triageReportCount={3} />);

    expect(screen.getByRole("button", { name: "Triage mode" })).toHaveAttribute(
      "href",
      "/inbox/triage",
    );
  });

  it("drops out of the header while triage is open", () => {
    mocks.pathname = "/inbox/triage";

    render(<InboxTriageButton triageReportCount={3} />);

    expect(screen.queryByText("Triage mode")).toBeNull();
  });
});
