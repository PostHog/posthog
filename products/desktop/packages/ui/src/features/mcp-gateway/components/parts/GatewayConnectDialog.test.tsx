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

  it("asks a custom api-key server's member for their own key without offering a choice", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <Theme>
        <GatewayConnectDialog
          open
          serverName="Internal Wiki"
          fixedAuthType="api_key"
          isCustomServer
          onSubmit={onSubmit}
          onClose={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.queryByText("Authentication")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "This server uses an API key. Enter your own key to connect.",
      ),
    ).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Enter API key"), "sk-mine");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(onSubmit).toHaveBeenCalledWith({
      authType: "api_key",
      apiKey: "sk-mine",
      clientId: "",
      clientSecret: "",
    });
  });

  it("keeps the optional OAuth client for a custom OAuth server without offering a choice", () => {
    render(
      <Theme>
        <GatewayConnectDialog
          open
          serverName="Internal Wiki"
          fixedAuthType="oauth"
          isCustomServer
          onSubmit={vi.fn()}
          onClose={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.queryByText("Authentication")).not.toBeInTheDocument();
    expect(screen.getByText("Optional")).toBeInTheDocument();
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

    await user.type(screen.getByPlaceholderText("Enter API key"), "sk-secret");
    await user.click(connect);

    expect(onSubmit).toHaveBeenCalledWith({
      authType: "api_key",
      apiKey: "sk-secret",
      clientId: "",
      clientSecret: "",
    });
  });
});
