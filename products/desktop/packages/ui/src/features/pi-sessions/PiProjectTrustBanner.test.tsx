import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PiProjectTrustBanner } from "./PiProjectTrustBanner";

describe("PiProjectTrustBanner", () => {
  it("warns before trusting and invokes the trust callback", async () => {
    const user = userEvent.setup();
    const onTrust = vi.fn(async () => {});

    render(
      <PiProjectTrustBanner
        trusted={false}
        disabled={false}
        pending={false}
        onTrust={onTrust}
        onRevoke={vi.fn(async () => {})}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Trust repository" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "run arbitrary code with your full user permissions",
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "access files and credentials",
    );

    await user.click(
      screen.getByRole("button", { name: "Trust and restart Pi" }),
    );
    await waitFor(() => expect(onTrust).toHaveBeenCalledOnce());
  });

  it("revokes trust without the dangerous confirmation", async () => {
    const user = userEvent.setup();
    const onRevoke = vi.fn(async () => {});

    render(
      <PiProjectTrustBanner
        trusted
        disabled={false}
        pending={false}
        onTrust={vi.fn(async () => {})}
        onRevoke={onRevoke}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Revoke trust" }));

    expect(onRevoke).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it.each([
    { disabled: true, pending: false },
    { disabled: false, pending: true },
  ])(
    "disables trust changes when disabled=$disabled and pending=$pending",
    ({ disabled, pending }) => {
      render(
        <PiProjectTrustBanner
          trusted={false}
          disabled={disabled}
          pending={pending}
          onTrust={vi.fn(async () => {})}
          onRevoke={vi.fn(async () => {})}
        />,
      );

      expect(
        screen.getByRole("button", { name: "Trust repository" }),
      ).toHaveAttribute("aria-disabled", "true");
    },
  );
});
