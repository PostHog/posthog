import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CanvasConnectorPermissionPrompt } from "./CanvasConnectorPermissionPrompt";

describe("canvas connector permission prompt", () => {
  it.each(["Deny", "Allow once", "Escape"])(
    "resolves a tool request with %s",
    async (action) => {
      const user = userEvent.setup();
      const onRespond = vi.fn();
      render(
        <CanvasConnectorPermissionPrompt
          request={{
            provider: "mcp:calendar.example.com",
            tool: "list_events",
            arguments: { limit: 5 },
            reason: "tool",
          }}
          onRespond={onRespond}
        />,
      );
      expect(
        screen.getByRole("dialog", { name: "Allow this tool call?" }),
      ).toBeInTheDocument();
      expect(screen.getByText("mcp:calendar.example.com")).toBeInTheDocument();
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Deny" })).toHaveFocus(),
      );
      await user.click(screen.getByText("Call arguments"));
      expect(screen.getByText(/"limit": 5/)).toBeVisible();
      if (action === "Escape") await user.keyboard("{Escape}");
      else await user.click(screen.getByRole("button", { name: action }));
      expect(onRespond).toHaveBeenCalledWith(action === "Allow once");
    },
  );
});
