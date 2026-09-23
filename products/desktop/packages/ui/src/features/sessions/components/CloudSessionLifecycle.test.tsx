import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CloudStreamDisconnectedBanner } from "./CloudSessionLifecycle";

describe("CloudStreamDisconnectedBanner", () => {
  it("uses the recovery action label", () => {
    render(
      <CloudStreamDisconnectedBanner
        onRetry={vi.fn()}
        retryLabel="Connect GitHub"
      />,
    );

    expect(
      screen.getByRole("button", { name: "Connect GitHub" }),
    ).toBeInTheDocument();
  });
});
