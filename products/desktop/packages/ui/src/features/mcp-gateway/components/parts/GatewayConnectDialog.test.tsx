import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GatewayConnectDialog } from "./GatewayConnectDialog";

describe("GatewayConnectDialog", () => {
  it("lets the member pick the mechanism for a custom server, defaulting to OAuth", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <Theme>
        <GatewayConnectDialog
          open
          serverName="Internal Wiki"
          fixedAuthType={null}
          onSubmit={onSubmit}
          onClose={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.getByText("Authentication")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(onSubmit).toHaveBeenCalledWith({
      authType: "oauth",
      apiKey: "",
      clientId: "",
      clientSecret: "",
    });
  });

  it("requires the key for an api-key server and submits it", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <Theme>
        <GatewayConnectDialog
          open
          serverName="Linear"
          fixedAuthType="api_key"
          onSubmit={onSubmit}
          onClose={vi.fn()}
        />
      </Theme>,
    );

    // The template fixes the mechanism, so there is nothing to choose.
    expect(screen.queryByText("Authentication")).not.toBeInTheDocument();
    const connect = screen.getByRole("button", { name: "Connect" });
    expect(connect).toBeDisabled();

    await user.type(screen.getByPlaceholderText("sk-…"), "sk-secret");
    await user.click(connect);

    expect(onSubmit).toHaveBeenCalledWith({
      authType: "api_key",
      apiKey: "sk-secret",
      clientId: "",
      clientSecret: "",
    });
  });
});
