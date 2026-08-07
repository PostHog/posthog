import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentPluginsView } from "./AgentPluginsView";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  refetch: vi.fn(),
  select: vi.fn(),
  register: vi.fn(),
  setEnabled: vi.fn(),
  unregister: vi.fn(),
}));

vi.mock("./useAgentPlugins", () => ({
  useAgentPlugins: () => mocks.list(),
  useSelectAgentPlugin: () => ({
    data: undefined,
    error: null,
    isPending: false,
    mutate: mocks.select,
    reset: vi.fn(),
  }),
  useRegisterAgentPlugin: () => ({
    error: null,
    isPending: false,
    mutate: mocks.register,
  }),
  useSetAgentPluginEnabled: () => ({
    error: null,
    isPending: false,
    mutate: mocks.setEnabled,
  }),
  useUnregisterAgentPlugin: () => ({
    error: null,
    isPending: false,
    variables: undefined,
    mutate: mocks.unregister,
  }),
}));

describe("AgentPluginsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a retry action when the installed plugin list fails", async () => {
    mocks.refetch.mockResolvedValue(undefined);
    mocks.list.mockReturnValue({
      data: undefined,
      error: new Error("Agent Plugin installation data is invalid."),
      isError: true,
      isFetching: false,
      isLoading: false,
      refetch: mocks.refetch,
    });

    render(<AgentPluginsView />);

    expect(
      screen.getByText("Could not load Agent Plugins"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No Agent Plugins added"),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Try again"));
    expect(mocks.refetch).toHaveBeenCalledOnce();
  });

  it("shows diagnostic paths and messages for installed plugins", () => {
    mocks.list.mockReturnValue({
      data: [
        {
          id: "0123456789abcdef",
          sourcePath: "/plugins/example",
          enabled: true,
          manifest: {
            $schema:
              "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            name: "example-plugin",
          },
          skills: [],
          diagnostics: [
            {
              severity: "error",
              code: "invalid_skill",
              path: "skills/broken/SKILL.md",
              message: "SKILL.md is not valid YAML.",
            },
          ],
        },
      ],
      error: null,
      isError: false,
      isFetching: false,
      isLoading: false,
      refetch: mocks.refetch,
    });

    render(<AgentPluginsView />);

    expect(
      screen.getByText("skills/broken/SKILL.md: SKILL.md is not valid YAML."),
    ).toBeInTheDocument();
  });
});
