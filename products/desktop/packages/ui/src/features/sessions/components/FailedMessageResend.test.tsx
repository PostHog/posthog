import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FailedMessageResendAction } from "./FailedMessageResend";

describe("FailedMessageResendAction", () => {
  it("sends once while the new message is submitting", async () => {
    let finishSend: () => void = () => {};
    const onResend = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishSend = resolve;
        }),
    );
    render(<FailedMessageResendAction onResend={onResend} />);

    const resend = screen.getByRole("button", { name: "Resend" });
    fireEvent.click(resend);
    fireEvent.click(resend);

    expect(onResend).toHaveBeenCalledOnce();
    expect(resend).toHaveAttribute("data-disabled");
    await act(async () => finishSend());
    expect(resend).not.toHaveAttribute("data-disabled");
  });

  it("does not offer a text-only copy when attachments are unavailable", () => {
    render(<FailedMessageResendAction resendable={false} onResend={vi.fn()} />);
    expect(
      screen.queryByRole("button", { name: "Resend" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Attached files unavailable/)).toBeInTheDocument();
  });

  it("does not offer an incomplete copy of a shortened message", () => {
    render(<FailedMessageResendAction truncated onResend={vi.fn()} />);
    expect(
      screen.queryByRole("button", { name: "Resend" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Message shortened/)).toBeInTheDocument();
  });
});
