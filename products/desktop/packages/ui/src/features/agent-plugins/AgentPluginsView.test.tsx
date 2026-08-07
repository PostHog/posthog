import type { AgentPluginInstallation } from "@posthog/core/agent-plugins/agentPluginsClient";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentPluginsView, escapeApprovalToken } from "./AgentPluginsView";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  refetch: vi.fn(),
  select: vi.fn(),
  register: vi.fn(),
  approveStdio: vi.fn(),
  setEnabled: vi.fn(),
  unregister: vi.fn(),
  unregisterPending: false,
  unregisterVariables: undefined as { id: string } | undefined,
}));

function installedPlugin(
  overrides: Partial<AgentPluginInstallation> = {},
): AgentPluginInstallation {
  return {
    id: "0123456789abcdef",
    sourcePath: "/plugins/example",
    enabled: true,
    manifest: {
      $schema: "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
      name: "example-plugin",
    },
    skills: [],
    mcpServers: [],
    stdioApprovalRequired: false,
    diagnostics: [],
    ...overrides,
  };
}

function mockPluginList(plugin: AgentPluginInstallation): void {
  mocks.list.mockReturnValue({
    data: [plugin],
    error: null,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: mocks.refetch,
  });
}

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
  useApproveAgentPluginStdio: () => ({
    error: null,
    isPending: false,
    variables: undefined,
    mutate: mocks.approveStdio,
  }),
  useSetAgentPluginEnabled: () => ({
    error: null,
    isPending: false,
    mutate: mocks.setEnabled,
  }),
  useUnregisterAgentPlugin: () => ({
    error: null,
    isPending: mocks.unregisterPending,
    variables: mocks.unregisterVariables,
    mutate: mocks.unregister,
  }),
}));

describe("AgentPluginsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.unregisterPending = false;
    mocks.unregisterVariables = undefined;
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

  it("renders stdio approval values as separate escaped tokens", () => {
    const command = "node tool\n\u202etail";
    const firstArgument = "argument one";
    const secondArgument = "--flag=two words";
    const cwd = "./working directory";
    const environmentName = "CONFIG\u2066NAME";
    mockPluginList(
      installedPlugin({
        stdioApprovalRequired: true,
        mcpServers: [
          {
            name: "local-server",
            type: "stdio",
            supported: true,
            command,
            args: [firstArgument, secondArgument],
            cwd,
            envNames: [environmentName],
            digest: "digest",
            approval: "required",
          },
        ],
      }),
    );

    render(<AgentPluginsView />);

    expect(escapeApprovalToken(command)).toBe('"node tool\\n\\u202etail"');
    for (const token of [
      command,
      firstArgument,
      secondArgument,
      cwd,
      environmentName,
    ]) {
      expect(screen.getByText(escapeApprovalToken(token))).toBeInTheDocument();
    }
    expect(screen.getByText("Argument 1")).toBeInTheDocument();
    expect(screen.getByText("Argument 2")).toBeInTheDocument();
    expect(screen.queryByText(`${firstArgument} ${secondArgument}`)).toBeNull();
  });

  it("confirms removal and blocks submission while removal is pending", async () => {
    mockPluginList(installedPlugin());
    const view = render(<AgentPluginsView />);

    await userEvent.click(screen.getByLabelText("Remove example-plugin"));
    expect(screen.getByText("Remove example-plugin?")).toBeInTheDocument();
    expect(
      screen.getByText(
        "The plugin's source files remain on disk. PostHog Desktop permanently removes its app-managed plugin data.",
      ),
    ).toBeInTheDocument();

    mocks.unregisterPending = true;
    mocks.unregisterVariables = { id: "0123456789abcdef" };
    view.rerender(<AgentPluginsView />);
    expect(screen.getByText("Remove plugin")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await userEvent.click(screen.getByText("Remove plugin"));
    expect(mocks.unregister).not.toHaveBeenCalled();

    mocks.unregisterPending = false;
    view.rerender(<AgentPluginsView />);
    await userEvent.click(screen.getByText("Remove plugin"));
    expect(mocks.unregister).toHaveBeenCalledOnce();
    expect(mocks.unregister).toHaveBeenCalledWith(
      { id: "0123456789abcdef" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
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
          mcpServers: [],
          stdioApprovalRequired: false,
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
