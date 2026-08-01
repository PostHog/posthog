import type {
  McpRecommendedServer,
  McpServerInstallation,
} from "@posthog/api-client/posthog-client";
import { useLocalMcpCloudServers } from "@posthog/ui/features/local-mcp/useLocalMcpCloudServers";
import { AddCustomServerForm } from "@posthog/ui/features/mcp-server-manager/AddCustomServerForm";
import { MarketplaceView } from "@posthog/ui/features/mcp-servers/components/parts/MarketplaceView";
import { McpInstalledRail } from "@posthog/ui/features/mcp-servers/components/parts/McpInstalledRail";
import { useMcpServers } from "@posthog/ui/features/mcp-servers/hooks/useMcpServers";
import {
  AlertDialog,
  Box,
  Button,
  Flex,
  ScrollArea,
  Spinner,
  Text,
} from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ServerDetailView } from "./parts/ServerDetailView";

type SceneView =
  | { kind: "marketplace" }
  | { kind: "detail-installation"; installationId: string }
  | { kind: "detail-template"; templateId: string }
  | { kind: "add-custom" };

export function McpServersView() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<SceneView>({ kind: "marketplace" });
  const [query, setQuery] = useState("");
  const [category, setCategory] =
    useState<Parameters<typeof MarketplaceView>[0]["category"]>("all");
  const [uninstallTarget, setUninstallTarget] =
    useState<McpServerInstallation | null>(null);
  // Snapshot of installation IDs taken when the user submits the Add Custom
  // form. The new installation is whichever id appears that wasn't in the
  // snapshot — robust against backend URL normalisation that would break a
  // string-equality match on `installation.url`.
  const [pendingCustomKnownIds, setPendingCustomKnownIds] =
    useState<Set<string> | null>(null);
  const [pendingTemplateId, setPendingTemplateId] = useState<string | null>(
    null,
  );

  const {
    installations,
    installationsLoading,
    servers,
    serversLoading,
    installingId,
    uninstallMutation,
    toggleEnabled,
    installTemplate,
    installCustom,
    installCustomPending,
    reauthorize,
    reauthorizePending,
  } = useMcpServers();

  const { servers: localServers } = useLocalMcpCloudServers(true);

  useEffect(() => {
    const refreshMcpState = () => {
      queryClient.invalidateQueries({ queryKey: ["mcp"] });
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") refreshMcpState();
    };
    window.addEventListener("focus", refreshMcpState);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("focus", refreshMcpState);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [queryClient]);

  const serverList = servers ?? [];
  const installationList = installations ?? [];

  const selectedInstallation = useMemo<McpServerInstallation | null>(() => {
    if (view.kind !== "detail-installation") return null;
    return installationList.find((i) => i.id === view.installationId) ?? null;
  }, [view, installationList]);

  const selectedTemplate = useMemo<McpRecommendedServer | null>(() => {
    if (view.kind === "detail-template") {
      return serverList.find((s) => s.id === view.templateId) ?? null;
    }
    if (view.kind === "detail-installation" && selectedInstallation) {
      return (
        serverList.find((s) => s.id === selectedInstallation.template_id) ??
        null
      );
    }
    return null;
  }, [view, serverList, selectedInstallation]);

  const handleConnect = useCallback(
    (template: McpRecommendedServer) => {
      setPendingTemplateId(template.id);
      installTemplate(template);
    },
    [installTemplate],
  );

  const handleUninstallConfirm = useCallback(() => {
    if (!uninstallTarget) return;
    uninstallMutation.mutate(uninstallTarget.id, {
      onSuccess: () => {
        setUninstallTarget(null);
        setView({ kind: "marketplace" });
      },
    });
  }, [uninstallTarget, uninstallMutation]);

  // When installations list updates, if the opened installation disappears, go back.
  useEffect(() => {
    if (
      view.kind === "detail-installation" &&
      !installationList.some((i) => i.id === view.installationId)
    ) {
      setView({ kind: "marketplace" });
    }
  }, [view, installationList]);

  // When viewing a template and it gets installed, switch to the installation
  // detail so the freshly-fetched tools and status render.
  useEffect(() => {
    if (view.kind !== "detail-template") return;
    const installation = installationList.find(
      (i) => i.template_id === view.templateId,
    );
    if (installation) {
      setView({ kind: "detail-installation", installationId: installation.id });
    }
  }, [view, installationList]);

  // After a custom server install resolves, jump to its detail panel once the
  // new installation appears in the list. Identifies the new one as any id
  // not present in the pre-submit snapshot — does not rely on URL equality.
  useEffect(() => {
    if (!pendingCustomKnownIds) return;
    const newOne = installationList.find(
      (i) => !pendingCustomKnownIds.has(i.id),
    );
    if (newOne) {
      setPendingCustomKnownIds(null);
      setView({ kind: "detail-installation", installationId: newOne.id });
    }
  }, [pendingCustomKnownIds, installationList]);

  // After a template install resolves, jump to the new installation's detail
  // panel. Stays put if the install fails (no matching installation appears).
  useEffect(() => {
    if (!pendingTemplateId) return;
    const installation = installationList.find(
      (i) => i.template_id === pendingTemplateId,
    );
    if (installation) {
      setPendingTemplateId(null);
      setView({ kind: "detail-installation", installationId: installation.id });
    }
  }, [pendingTemplateId, installationList]);

  const selectedInstallationId =
    view.kind === "detail-installation" ? view.installationId : null;

  const mainContent = (() => {
    if (view.kind === "add-custom") {
      return (
        <AddCustomServerForm
          pending={installCustomPending}
          onBack={() => setView({ kind: "marketplace" })}
          onSubmit={(values) => {
            setPendingCustomKnownIds(
              new Set(installationList.map((i) => i.id)),
            );
            installCustom(values, {
              onError: () => setPendingCustomKnownIds(null),
            });
          }}
        />
      );
    }

    if (
      view.kind === "detail-installation" ||
      view.kind === "detail-template"
    ) {
      const install =
        view.kind === "detail-installation" ? selectedInstallation : null;
      const template = selectedTemplate;

      if (!install && !template) {
        return (
          <Flex align="center" justify="center" py="6">
            {installationsLoading || serversLoading ? (
              <Spinner size="2" />
            ) : (
              <Text color="gray" className="text-sm">
                Server not found.
              </Text>
            )}
          </Flex>
        );
      }

      return (
        <ServerDetailView
          installation={install}
          template={template}
          isEnabled={install?.is_enabled !== false}
          isInstalling={!!template && installingId === template.id && !install}
          isReauthorizing={reauthorizePending}
          onBack={() => setView({ kind: "marketplace" })}
          onConnect={() => {
            if (template) {
              setPendingTemplateId(template.id);
              installTemplate(template);
            }
          }}
          onReauthorize={() => {
            if (install) reauthorize(install.id);
          }}
          onToggleEnabled={(enabled) => {
            if (install) toggleEnabled(install.id, enabled);
          }}
          onUninstall={() => {
            if (install) setUninstallTarget(install);
          }}
        />
      );
    }

    return (
      <MarketplaceView
        servers={serverList}
        serversLoading={serversLoading}
        installations={installationList}
        installingId={installingId}
        query={query}
        onQueryChange={setQuery}
        category={category}
        onCategoryChange={setCategory}
        onOpenServer={(templateId) =>
          setView({ kind: "detail-template", templateId })
        }
        onOpenInstallation={(installationId) =>
          setView({ kind: "detail-installation", installationId })
        }
        onConnect={handleConnect}
        onAddCustom={() => setView({ kind: "add-custom" })}
      />
    );
  })();

  return (
    <Flex height="100%" className="min-h-0 overflow-hidden">
      <McpInstalledRail
        installations={installationList}
        templates={serverList}
        localServers={localServers}
        selectedInstallationId={selectedInstallationId}
        onAddCustom={() => setView({ kind: "add-custom" })}
        onSelectInstallation={(installationId) =>
          setView({ kind: "detail-installation", installationId })
        }
      />
      <Box className="min-h-0 min-w-0 flex-1">
        <ScrollArea className="h-full w-full">
          <Box p="6" mx="auto" className="relative z-[1] max-w-[960px]">
            {mainContent}
          </Box>
        </ScrollArea>
      </Box>
      <UninstallConfirmDialog
        target={uninstallTarget}
        isPending={uninstallMutation.isPending}
        onCancel={() => setUninstallTarget(null)}
        onConfirm={handleUninstallConfirm}
      />
    </Flex>
  );
}

function UninstallConfirmDialog({
  target,
  isPending,
  onCancel,
  onConfirm,
}: {
  target: McpServerInstallation | null;
  isPending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const open = !!target;
  const name =
    target?.display_name || target?.name || target?.url || "this server";
  return (
    <AlertDialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <AlertDialog.Content maxWidth="450px">
        <AlertDialog.Title>Remove MCP server</AlertDialog.Title>
        <AlertDialog.Description className="text-sm">
          Are you sure you want to remove{" "}
          <Text className="font-bold">{name}</Text>? This will revoke its tools
          from your agent.
        </AlertDialog.Description>
        <Flex gap="3" mt="4" justify="end">
          <AlertDialog.Cancel>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </AlertDialog.Cancel>
          <AlertDialog.Action>
            <Button
              variant="solid"
              color="red"
              onClick={onConfirm}
              disabled={isPending}
            >
              {isPending ? <Spinner size="1" /> : null}
              Remove
            </Button>
          </AlertDialog.Action>
        </Flex>
      </AlertDialog.Content>
    </AlertDialog.Root>
  );
}
