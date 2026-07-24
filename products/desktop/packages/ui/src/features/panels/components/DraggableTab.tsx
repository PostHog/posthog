import { useSortable } from "@dnd-kit/react/sortable";
import { resolveWorkspaceForRepoPath } from "@posthog/core/panels/resolveWorkspaceForRepoPath";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useExternalAppAction } from "@posthog/ui/features/external-apps/useExternalAppAction";
import type { TabData } from "@posthog/ui/features/panels/panelTypes";
import { Cross2Icon } from "@radix-ui/react-icons";
import { Box, Flex, IconButton, Text } from "@radix-ui/themes";
import type React from "react";
import { useCallback } from "react";

interface DraggableTabProps {
  tabId: string;
  panelId: string;
  label: string;
  tabData: TabData;
  isActive: boolean;
  index: number;
  draggable?: boolean;
  closeable?: boolean;
  isPreview?: boolean;
  onSelect: () => void;
  onClose?: () => void;
  onCloseOthers?: () => void;
  onCloseToRight?: () => void;
  onKeep?: () => void;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  hasUnsavedChanges?: boolean;
}

export const DraggableTab: React.FC<DraggableTabProps> = ({
  tabId,
  panelId,
  label,
  tabData,
  isActive,
  index,
  draggable = true,
  closeable = true,
  isPreview,
  onSelect,
  onClose,
  onCloseOthers,
  onCloseToRight,
  onKeep,
  icon,
  badge,
  hasUnsavedChanges,
}) => {
  const hostClient = useHostTRPCClient();
  const openExternalApp = useExternalAppAction();

  const { ref, isDragging } = useSortable({
    id: tabId,
    index,
    group: panelId,
    disabled: !draggable,
    transition: {
      duration: 200,
      easing: "ease",
    },
    data: { tabId, panelId, type: "tab" },
  });

  const handleDoubleClick = useCallback(() => {
    if (isPreview) {
      onKeep?.();
    }
  }, [isPreview, onKeep]);

  const handleContextMenu = useCallback(
    async (e: React.MouseEvent) => {
      e.preventDefault();

      const filePath =
        tabData.type === "file" ? tabData.absolutePath : undefined;
      const repoPath = tabData.type === "file" ? tabData.repoPath : undefined;

      const result = await hostClient.contextMenu.showTabContextMenu.mutate({
        canClose: closeable,
        filePath,
      });

      if (!result.action) return;

      switch (result.action.type) {
        case "close":
          onClose?.();
          break;
        case "close-others":
          onCloseOthers?.();
          break;
        case "close-right":
          onCloseToRight?.();
          break;
        case "external-app": {
          if (filePath) {
            const workspaces = await hostClient.workspace.getAll.query();
            const workspace = resolveWorkspaceForRepoPath(workspaces, repoPath);
            await openExternalApp(result.action.action, filePath, label, {
              workspace,
              mainRepoPath: workspace?.folderPath,
            });
          }
          break;
        }
      }
    },
    [
      closeable,
      onClose,
      onCloseOthers,
      onCloseToRight,
      tabData,
      label,
      hostClient,
      openExternalApp,
    ],
  );

  return (
    <Flex
      ref={ref}
      role="tab"
      aria-label={label}
      data-tab-id={tabId}
      data-active={isActive}
      align="center"
      gap="1"
      pl="3"
      pr={onClose ? "2" : "3"}
      className={`group relative h-[32px] min-w-[60px] flex-shrink-0 select-none border-r border-b-2 transition-colors ${draggable ? "cursor-grab" : "cursor-pointer"}`}
      style={{
        borderRightColor: "var(--gray-6)",
        borderBottomColor: isActive ? "var(--accent-10)" : "transparent",
        color: isActive ? "var(--accent-12)" : "var(--gray-11)",
        opacity: isDragging ? 0.5 : 1,
      }}
      onClick={onSelect}
      onDoubleClick={handleDoubleClick}
      onContextMenu={handleContextMenu}
      onMouseEnter={(e) => {
        if (!isActive) {
          e.currentTarget.style.color = "var(--gray-12)";
        }
      }}
      onMouseLeave={(e) => {
        if (!isActive) {
          e.currentTarget.style.color = "var(--gray-11)";
        }
      }}
    >
      {icon && <Box className="flex items-center">{icon}</Box>}
      <Text
        className="max-w-[200px] select-none overflow-hidden text-ellipsis whitespace-nowrap text-[13px]"
        style={{
          fontStyle: isPreview ? "italic" : "normal",
          opacity: isPreview ? 0.7 : 1,
        }}
      >
        {label}
      </Text>
      {badge}
      {hasUnsavedChanges && (
        <Text className="ml-[2px] text-(--amber-9) text-[13px]">•</Text>
      )}

      {onClose && (
        <Box className="ml-[2px] flex w-[14px] items-center justify-center">
          <IconButton
            size="1"
            variant="ghost"
            color={isActive ? undefined : "gray"}
            className={`transition-opacity ${isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
            aria-label="Close tab"
            onClick={(e) => {
              e.stopPropagation();
              onClose();
            }}
          >
            <Cross2Icon width={12} height={12} />
          </IconButton>
        </Box>
      )}
    </Flex>
  );
};
