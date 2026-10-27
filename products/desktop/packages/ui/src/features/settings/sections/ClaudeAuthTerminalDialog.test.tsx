import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const TOKEN = "sk-ant-oat01-fake-test-token-0123456789abcdefghijABCDEFGHIJ";

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    agent: {
      claudeAuthTerminal: {
        queryOptions: () => ({
          queryKey: ["claude-auth-terminal"],
          queryFn: async () => ({
            command: "claude setup-token",
            cwd: "/tmp",
            additionalEnv: {},
            unsetEnv: [],
          }),
        }),
      },
      claudeSubscriptionStatus: {
        queryOptions: () => ({
          queryKey: ["claude-subscription-status"],
          queryFn: async () => ({ loginState: "logged-in" }),
        }),
      },
    },
  }),
}));

vi.mock("@posthog/ui/features/terminal/destroyShellTerminal", () => ({
  destroyTerminalSession: vi.fn(),
}));

vi.mock("@posthog/ui/features/settings/components/AuthTerminalPanel", () => ({
  AuthTerminalPanel: ({
    onExit,
    onOutput,
  }: {
    onExit: (exitCode?: number) => void;
    onOutput?: (data: string) => void;
  }) => (
    <div>
      <button type="button" onClick={() => onOutput?.(`\r\n${TOKEN}\r\n`)}>
        Print token
      </button>
      <button type="button" onClick={() => onExit(0)}>
        Exit ok
      </button>
      <button type="button" onClick={() => onExit(1)}>
        Exit failed
      </button>
    </div>
  ),
}));

import { ClaudeAuthTerminalDialog } from "./ClaudeAuthTerminalDialog";

describe("ClaudeAuthTerminalDialog", () => {
  it.each([
    {
      printsToken: true,
      exit: "Exit ok",
      offersSave: true,
      hint: "Desktop found a new Claude token. Save it for your cloud tasks?",
    },
    {
      printsToken: true,
      exit: "Exit failed",
      offersSave: false,
      hint: "Token setup did not finish. Read the terminal output, then try again.",
    },
    {
      printsToken: false,
      exit: "Exit ok",
      offersSave: false,
      hint: "Copy the token. Close this window, then paste the token into Cloud tasks.",
    },
  ])(
    "offers to save a token only when setup ends with a token (%o)",
    async ({ printsToken, exit, offersSave, hint }) => {
      const user = userEvent.setup();
      const onSaveToken = vi.fn();
      render(
        <QueryClientProvider client={new QueryClient()}>
          <ClaudeAuthTerminalDialog
            action="setup-token"
            onClose={vi.fn()}
            onSaveToken={onSaveToken}
          />
        </QueryClientProvider>,
      );

      if (printsToken) {
        await user.click(await screen.findByText("Print token"));
      }
      await user.click(await screen.findByText(exit));

      expect(await screen.findByText(hint)).toBeInTheDocument();
      expect(screen.queryByText(TOKEN)).not.toBeInTheDocument();
      const save = screen.queryByRole("button", { name: "Save token" });
      if (offersSave) {
        await user.click(save as HTMLElement);
        expect(onSaveToken).toHaveBeenCalledExactlyOnceWith(TOKEN);
      } else {
        expect(save).not.toBeInTheDocument();
      }
    },
  );
});
