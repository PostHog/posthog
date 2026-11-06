import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GithubConnectionRequiredDialog } from "./GithubConnectionRequiredDialog";

const mockToastError = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: mockToastError },
}));

describe("GithubConnectionRequiredDialog", () => {
  it("offers connection, explains access, and copies the admin request", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(
      <GithubConnectionRequiredDialog
        open
        isConnecting={false}
        canRunLocally
        onOpenChange={() => undefined}
        onConnect={() => undefined}
        onRunLocally={() => undefined}
      />,
    );

    expect(
      document.querySelector('[data-attr="connect-github-for-code-context"]'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Connect GitHub to run this cloud task with code context.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Run with local code snapshot"),
    ).toBeInTheDocument();

    await user.click(screen.getByText("Why do I need this?"));
    const request =
      "PostHog needs read access to diagnose product changes using code context and keep investigations current. When a task changes code, it also needs permission to create branches and open pull requests for review.";
    expect(screen.getByText(request)).toBeInTheDocument();

    await user.click(screen.getByLabelText("Copy access request"));
    expect(writeText).toHaveBeenCalledWith(request);
    expect(screen.getByLabelText("Access request copied")).toBeInTheDocument();
  });

  it("shows the copyable request when GitHub is waiting for approval", () => {
    render(
      <GithubConnectionRequiredDialog
        open
        isConnecting={false}
        approvalPending
        canRunLocally={false}
        onOpenChange={() => undefined}
        onConnect={() => undefined}
        onRunLocally={() => undefined}
      />,
    );

    expect(
      screen.getByText(
        "PostHog needs read access to diagnose product changes using code context and keep investigations current. When a task changes code, it also needs permission to create branches and open pull requests for review.",
      ),
    ).toBeInTheDocument();
  });

  it("reports a clipboard failure without showing copied state", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("blocked")) },
    });

    render(
      <GithubConnectionRequiredDialog
        open
        isConnecting={false}
        approvalPending
        canRunLocally={false}
        onOpenChange={() => undefined}
        onConnect={() => undefined}
        onRunLocally={() => undefined}
      />,
    );

    await user.click(screen.getByLabelText("Copy access request"));

    expect(mockToastError).toHaveBeenCalledWith(
      "Couldn't copy the access request",
    );
  });
});
