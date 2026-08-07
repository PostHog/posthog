import { FolderOpen, Package, Trash, Warning } from "@phosphor-icons/react";
import type { AgentPluginMcpServerSummary } from "@posthog/core/agent-plugins/agentPluginsClient";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Switch,
  Text,
} from "@posthog/quill";
import { type ReactElement, useState } from "react";
import {
  useAgentPlugins,
  useApproveAgentPluginStdio,
  useRegisterAgentPlugin,
  useSelectAgentPlugin,
  useSetAgentPluginEnabled,
  useUnregisterAgentPlugin,
} from "./useAgentPlugins";

function errorMessage(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

function diagnosticText(item: { message: string; path?: string }): string {
  return item.path ? `${item.path}: ${item.message}` : item.message;
}

const DIRECTIONAL_CONTROL_PATTERN = /[\u200e\u200f\u202a-\u202e\u2066-\u2069]/g;

export function escapeApprovalToken(value: string): string {
  return JSON.stringify(value).replace(
    DIRECTIONAL_CONTROL_PATTERN,
    (control) => `\\u${control.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
}

function ApprovalToken({
  label,
  value,
}: {
  label: string;
  value: string;
}): ReactElement {
  return (
    <div className="flex min-w-0 items-start gap-2">
      <Text size="xs" variant="muted" className="shrink-0">
        {label}
      </Text>
      <code
        dir="ltr"
        className="max-h-20 min-w-0 overflow-auto whitespace-pre-wrap break-all rounded bg-muted px-1 text-xs [unicode-bidi:isolate]"
      >
        {escapeApprovalToken(value)}
      </code>
    </div>
  );
}

function StdioApprovalDetails({
  server,
}: {
  server: AgentPluginMcpServerSummary;
}): ReactElement {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium">
          {server.name}
        </Text>
        {server.approval !== "not-required" && (
          <Badge
            variant={server.approval === "approved" ? "success" : "warning"}
          >
            {server.approval === "approved" ? "Approved" : "Review required"}
          </Badge>
        )}
      </div>
      <ApprovalToken label="Command" value={server.command ?? ""} />
      {(server.args ?? []).length > 0 ? (
        server.args?.map((argument, index) => (
          <ApprovalToken
            key={`${server.name}-argument-${index}`}
            label={`Argument ${index + 1}`}
            value={argument}
          />
        ))
      ) : (
        <Text size="xs" variant="muted">
          No arguments
        </Text>
      )}
      <ApprovalToken
        label="Working directory"
        value={server.cwd ?? "${PLUGIN_ROOT}"}
      />
      {(server.envNames ?? []).length > 0 ? (
        server.envNames?.map((name) => (
          <ApprovalToken
            key={`${server.name}-environment-${name}`}
            label="Environment variable"
            value={name}
          />
        ))
      ) : (
        <Text size="xs" variant="muted">
          No environment variables
        </Text>
      )}
    </div>
  );
}

export function AgentPluginsView(): ReactElement {
  const plugins = useAgentPlugins();
  const selectPlugin = useSelectAgentPlugin();
  const registerPlugin = useRegisterAgentPlugin();
  const approveStdio = useApproveAgentPluginStdio();
  const setEnabled = useSetAgentPluginEnabled();
  const unregister = useUnregisterAgentPlugin();
  const preview = selectPlugin.data;
  const [removeTarget, setRemoveTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const handleRegister = (): void => {
    if (!preview?.selectionToken) return;
    registerPlugin.mutate(
      { selectionToken: preview.selectionToken },
      { onSuccess: () => selectPlugin.reset() },
    );
  };

  const handleRemove = (): void => {
    if (!removeTarget || unregister.isPending) return;
    unregister.mutate(
      { id: removeTarget.id },
      { onSuccess: () => setRemoveTarget(null) },
    );
  };

  return (
    <>
      <div className="h-full min-h-0 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-1">
              <Text weight="semibold">Agent Plugins</Text>
              <Text size="sm" variant="muted">
                Add local Agent Plugins that provide portable skills, Streamable
                HTTP MCP servers, and stdio MCP servers.
              </Text>
            </div>
            <Button
              variant="primary"
              loading={selectPlugin.isPending}
              onClick={() => selectPlugin.mutate()}
            >
              <FolderOpen />
              Add local plugin
            </Button>
          </div>

          {preview && (
            <Card>
              <CardHeader>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex flex-col gap-1">
                    <CardTitle>
                      {preview.manifest?.name ?? "Invalid Agent Plugin"}
                    </CardTitle>
                    <CardDescription className="break-all">
                      {preview.sourcePath}
                    </CardDescription>
                  </div>
                  <Badge variant={preview.valid ? "success" : "destructive"}>
                    {preview.valid ? "Ready to add" : "Invalid"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col gap-4">
                  {preview.manifest?.description && (
                    <Text size="sm">{preview.manifest.description}</Text>
                  )}
                  <div className="flex flex-col gap-2">
                    <Text size="xs" variant="muted">
                      {preview.skills.length} valid skill
                      {preview.skills.length === 1 ? "" : "s"}
                    </Text>
                    <div className="flex flex-wrap gap-2">
                      {preview.skills.map((skill) => (
                        <Badge key={skill.path}>{skill.name}</Badge>
                      ))}
                    </div>
                    <Text size="xs" variant="muted">
                      {preview.mcpServers.length} MCP server
                      {preview.mcpServers.length === 1 ? "" : "s"}
                    </Text>
                    <div className="flex flex-wrap gap-2">
                      {preview.mcpServers.map((server) => (
                        <Badge key={server.name} variant="info">
                          {server.name} ·{" "}
                          {server.type === "stdio" ? "stdio" : "HTTP"}
                        </Badge>
                      ))}
                    </div>
                    {preview.mcpServers
                      .filter((server) => server.type === "stdio")
                      .map((server) => (
                        <StdioApprovalDetails
                          key={server.name}
                          server={server}
                        />
                      ))}
                    {preview.mcpServers.some(
                      (server) => server.type === "stdio",
                    ) && (
                      <Text size="xs" variant="muted">
                        Adding this plugin approves the stdio commands shown
                        above. PostHog Desktop will ask again if they change.
                      </Text>
                    )}
                  </div>
                  {preview.diagnostics.length > 0 && (
                    <div className="flex flex-col gap-2 rounded-md border border-border p-3">
                      {preview.diagnostics.map((item, index) => (
                        <div
                          key={`${item.code}-${item.path ?? "root"}-${index}`}
                          className="flex items-start gap-2"
                        >
                          <Warning className="mt-0.5 shrink-0" />
                          <Text
                            size="xs"
                            variant={
                              item.severity === "error"
                                ? "destructive"
                                : "muted"
                            }
                            className="break-all"
                          >
                            {diagnosticText(item)}
                          </Text>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex justify-end gap-2">
                    <Button
                      variant="outline"
                      onClick={() => selectPlugin.reset()}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      loading={registerPlugin.isPending}
                      disabled={!preview.valid || !preview.selectionToken}
                      onClick={handleRegister}
                    >
                      Add plugin
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {(errorMessage(selectPlugin.error) ||
            errorMessage(registerPlugin.error) ||
            errorMessage(approveStdio.error) ||
            errorMessage(setEnabled.error) ||
            errorMessage(unregister.error)) && (
            <Text variant="destructive" size="sm">
              {errorMessage(selectPlugin.error) ??
                errorMessage(registerPlugin.error) ??
                errorMessage(approveStdio.error) ??
                errorMessage(setEnabled.error) ??
                errorMessage(unregister.error)}
            </Text>
          )}

          {plugins.isLoading ? (
            <div className="flex justify-center p-8">
              <Spinner />
            </div>
          ) : plugins.isError ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Warning />
                </EmptyMedia>
                <EmptyTitle>Could not load Agent Plugins</EmptyTitle>
                <EmptyDescription>
                  {plugins.error.message} Try again. If it keeps happening,
                  contact support.
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button
                  variant="outline"
                  loading={plugins.isFetching}
                  onClick={() => void plugins.refetch()}
                >
                  Try again
                </Button>
              </EmptyContent>
            </Empty>
          ) : plugins.data?.length ? (
            <div className="flex flex-col gap-2">
              {plugins.data.map((plugin) => (
                <Card key={plugin.id} size="sm">
                  <CardContent>
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-3">
                        <Package className="shrink-0" />
                        <div className="min-w-0 flex-1">
                          <Text weight="medium">{plugin.manifest.name}</Text>
                          <Text
                            size="xs"
                            variant="muted"
                            className="block break-all"
                          >
                            {plugin.skills.length} skill
                            {plugin.skills.length === 1 ? "" : "s"} and{" "}
                            {plugin.mcpServers.length} MCP server
                            {plugin.mcpServers.length === 1 ? "" : "s"} from{" "}
                            {plugin.sourcePath}
                          </Text>
                        </div>
                        {plugin.diagnostics.length > 0 && (
                          <Badge variant="warning">
                            {plugin.diagnostics.length} diagnostic
                            {plugin.diagnostics.length === 1 ? "" : "s"}
                          </Badge>
                        )}
                        <Switch
                          checked={plugin.enabled}
                          disabled={
                            setEnabled.isPending ||
                            (!plugin.enabled && plugin.stdioApprovalRequired)
                          }
                          aria-label={`Enable ${plugin.manifest.name}`}
                          onCheckedChange={(enabled) =>
                            setEnabled.mutate({ id: plugin.id, enabled })
                          }
                        />
                        <Button
                          variant="destructive"
                          size="icon-sm"
                          disabled={unregister.isPending}
                          aria-label={`Remove ${plugin.manifest.name}`}
                          onClick={() =>
                            setRemoveTarget({
                              id: plugin.id,
                              name: plugin.manifest.name,
                            })
                          }
                        >
                          <Trash />
                        </Button>
                      </div>
                      {plugin.mcpServers
                        .filter((server) => server.type === "stdio")
                        .map((server) => (
                          <StdioApprovalDetails
                            key={server.name}
                            server={server}
                          />
                        ))}
                      {plugin.stdioApprovalRequired && (
                        <div className="flex justify-end">
                          <Button
                            variant="primary"
                            loading={
                              approveStdio.isPending &&
                              approveStdio.variables?.id === plugin.id
                            }
                            disabled={approveStdio.isPending}
                            onClick={() =>
                              approveStdio.mutate({ id: plugin.id })
                            }
                          >
                            Approve stdio commands
                          </Button>
                        </div>
                      )}
                      {plugin.diagnostics.length > 0 && (
                        <div className="flex flex-col gap-1 rounded-md border border-border p-3">
                          {plugin.diagnostics.map((item, index) => (
                            <Text
                              key={`${item.code}-${item.path ?? "root"}-${index}`}
                              size="xs"
                              variant={
                                item.severity === "error"
                                  ? "destructive"
                                  : "muted"
                              }
                              className="break-all"
                            >
                              {diagnosticText(item)}
                            </Text>
                          ))}
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Package />
                </EmptyMedia>
                <EmptyTitle>No Agent Plugins added</EmptyTitle>
                <EmptyDescription>
                  Choose a local plugin directory to make its valid skills and
                  MCP servers available to agents.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </div>
      </div>

      <AlertDialog
        open={removeTarget !== null}
        onOpenChange={(open) => {
          if (!open && !unregister.isPending) setRemoveTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Remove {removeTarget?.name ?? "this Agent Plugin"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              The plugin's source files remain on disk. PostHog Desktop
              permanently removes its app-managed plugin data.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button variant="outline" disabled={unregister.isPending}>
                  Cancel
                </Button>
              }
            />
            <Button
              variant="destructive"
              loading={unregister.isPending}
              disabled={unregister.isPending}
              onClick={handleRemove}
            >
              Remove plugin
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
