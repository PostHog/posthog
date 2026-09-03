import type { McpRecommendedServer } from "@posthog/api-client/posthog-client";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ServerCard } from "./ServerCard";

vi.mock("./icons", () => ({
  ServerIcon: () => <div aria-hidden="true" />,
}));

it("shows a coming-soon server without allowing connection", async () => {
  const user = userEvent.setup();
  const onConnect = vi.fn();
  const server = {
    id: "slack",
    name: "Slack",
    url: "https://mcp.slack.com/mcp",
    icon_domain: "slack.com",
    is_coming_soon: true,
  } as McpRecommendedServer;

  render(
    <Theme>
      <ServerCard
        server={server}
        installed={false}
        isInstalling={false}
        onOpen={vi.fn()}
        onConnect={onConnect}
      />
    </Theme>,
  );

  const button = screen.getByRole("button", { name: "Coming soon" });
  expect(button).toBeDisabled();
  await user.click(button);
  expect(onConnect).not.toHaveBeenCalled();
});
