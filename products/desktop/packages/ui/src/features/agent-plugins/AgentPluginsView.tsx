import { FolderOpen, Package, Trash, Warning } from "@phosphor-icons/react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Switch,
  Text,
} from "@posthog/quill";
import {
  useAgentPlugins,
  useRegisterAgentPlugin,
  useSelectAgentPlugin,
  useSetAgentPluginEnabled,
  useUnregisterAgentPlugin,
} from "./useAgentPlugins";

function errorMessage(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

export function AgentPluginsView() {
  const plugins = useAgentPlugins();
  const selectPlugin = useSelectAgentPlugin();
  const registerPlugin = useRegisterAgentPlugin();
  const setEnabled = useSetAgentPluginEnabled();
  const unregister = useUnregisterAgentPlugin();
  const preview = selectPlugin.data;

  const handleRegister = (): void => {
    if (!preview) return;
    registerPlugin.mutate(
      { sourcePath: preview.sourcePath },
      { onSuccess: () => selectPlugin.reset() },
    );
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <Text weight="semibold">Agent Plugins</Text>
          <Text size="sm" variant="muted">
            Add local Agent Plugins that provide portable skills. MCP servers
            are not supported yet.
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
              <div className="flex flex-wrap gap-2">
                {preview.skills.map((skill) => (
                  <Badge key={skill.path}>{skill.name}</Badge>
                ))}
                {preview.skills.length === 0 && (
                  <Text size="sm" variant="muted">
                    No valid skills found
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
                          item.severity === "error" ? "destructive" : "muted"
                        }
                      >
                        {item.message}
                      </Text>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => selectPlugin.reset()}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  loading={registerPlugin.isPending}
                  disabled={!preview.valid}
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
        errorMessage(setEnabled.error) ||
        errorMessage(unregister.error)) && (
        <Text variant="destructive" size="sm">
          {errorMessage(selectPlugin.error) ??
            errorMessage(registerPlugin.error) ??
            errorMessage(setEnabled.error) ??
            errorMessage(unregister.error)}
        </Text>
      )}

      {plugins.isLoading ? (
        <div className="flex justify-center p-8">
          <Spinner />
        </div>
      ) : plugins.data?.length ? (
        <div className="flex flex-col gap-2">
          {plugins.data.map((plugin) => (
            <Card key={plugin.id} size="sm">
              <CardContent>
                <div className="flex items-center gap-3">
                  <Package className="shrink-0" />
                  <div className="min-w-0 flex-1">
                    <Text weight="medium">{plugin.manifest.name}</Text>
                    <Text size="xs" variant="muted" className="block truncate">
                      {plugin.skills.length} valid skill
                      {plugin.skills.length === 1 ? "" : "s"} from{" "}
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
                    disabled={setEnabled.isPending}
                    aria-label={`Enable ${plugin.manifest.name}`}
                    onCheckedChange={(enabled) =>
                      setEnabled.mutate({ id: plugin.id, enabled })
                    }
                  />
                  <Button
                    variant="destructive"
                    size="icon-sm"
                    loading={
                      unregister.isPending &&
                      unregister.variables?.id === plugin.id
                    }
                    disabled={unregister.isPending}
                    aria-label={`Remove ${plugin.manifest.name}`}
                    onClick={() => unregister.mutate({ id: plugin.id })}
                  >
                    <Trash />
                  </Button>
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
              Choose a local plugin directory to make its valid skills available
              to agents.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
    </div>
  );
}
