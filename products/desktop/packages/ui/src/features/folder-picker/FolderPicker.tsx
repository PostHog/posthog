import {
  CaretDown,
  CircleNotch,
  Folder as FolderIcon,
  FolderOpen,
  GitBranch,
  GitFork,
  X,
} from "@phosphor-icons/react";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { useService } from "@posthog/di/react";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import type { RegisteredFolder } from "@posthog/ui/features/folders/types";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { toast } from "@posthog/ui/primitives/toast";
import { FIELD_TRIGGER_CLASS } from "@posthog/ui/styles/fieldTrigger";
import { Flex, Text } from "@radix-ui/themes";
import { useQueries } from "@tanstack/react-query";
import { type RefObject, useMemo, useState } from "react";

interface FolderRow {
  folder: RegisteredFolder;
  isWorktree: boolean;
  /** Rendered nested under its main clone (which is also in the list). */
  indented: boolean;
}

/**
 * Groups recent folders into repo families: a recent checkout pulls in its
 * main clone and every registered worktree of the same repo, main first,
 * worktrees indented beneath it. Standalone folders stay single rows.
 */
export function buildFolderRows(
  recentFolders: RegisteredFolder[],
  allFolders: RegisteredFolder[],
): FolderRow[] {
  const familyKey = (f: RegisteredFolder) => f.mainRepoPath ?? f.path;
  const emitted = new Set<string>();
  const rows: FolderRow[] = [];
  for (const recent of recentFolders) {
    const key = familyKey(recent);
    if (emitted.has(key)) continue;
    emitted.add(key);
    const members = allFolders.filter((f) => familyKey(f) === key);
    const main = members.find((f) => !f.mainRepoPath);
    const worktrees = members
      .filter((f) => f.mainRepoPath)
      .sort((a, b) => a.name.localeCompare(b.name));
    if (main) rows.push({ folder: main, isWorktree: false, indented: false });
    for (const wt of worktrees) {
      rows.push({ folder: wt, isWorktree: true, indented: !!main });
    }
  }
  return rows;
}

interface FolderPickerProps {
  value: string;
  onChange: (path: string) => void;
  placeholder?: string;
  variant?: "compact" | "field";
  anchor?: RefObject<HTMLElement | null>;
}

export function FolderPicker({
  value,
  onChange,
  placeholder = "Select folder...",
  variant = "compact",
  anchor,
}: FolderPickerProps) {
  const trpcClient = useHostTRPCClient();
  const trpc = useHostTRPC();
  const log = useService<RootLogger>(ROOT_LOGGER);
  const {
    folders,
    getRecentFolders,
    getFolderDisplayName,
    addFolder,
    removeFolder,
    updateLastAccessed,
    getFolderByPath,
  } = useFolders();

  const recentFolders = getRecentFolders();
  const displayValue = getFolderDisplayName(value);
  const isField = variant === "field";

  const [isOpening, setIsOpening] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const folderRows = useMemo(
    () => buildFolderRows(recentFolders, folders),
    [recentFolders, folders],
  );

  // Current branch per visible row, so the picker answers "what is checked
  // out where?" before committing to a folder. Only queried while open.
  const branchQueries = useQueries({
    queries: folderRows.map((row) => ({
      ...trpc.git.getCurrentBranch.queryOptions({
        directoryPath: row.folder.path,
      }),
      enabled: menuOpen,
      staleTime: 30_000,
    })),
  });
  const [pendingRemoval, setPendingRemoval] = useState<{
    id: string;
    name: string;
    path: string;
  } | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);

  const handleSelect = (path: string) => {
    onChange(path);
    const folder = getFolderByPath(path);
    if (folder) updateLastAccessed(folder.id);
  };

  const handleConfirmRemoval = async () => {
    if (!pendingRemoval) return;
    setIsRemoving(true);
    try {
      await removeFolder(pendingRemoval.id);
      if (pendingRemoval.path === value) onChange("");
      setPendingRemoval(null);
    } catch (error) {
      log.error("Failed to remove folder", { error });
      toast.error("Couldn't remove folder", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setIsRemoving(false);
    }
  };

  const handleOpenFilePicker = async () => {
    if (isOpening) return;
    setIsOpening(true);
    try {
      const selectedPath = await trpcClient.os.selectDirectory.query();
      if (!selectedPath) return;
      await addFolder(selectedPath);
      onChange(selectedPath);
    } catch (error) {
      log.error("Failed to open folder picker", { error });
    } finally {
      setIsOpening(false);
    }
  };

  const fieldContent = (
    <>
      <Flex align="center" gap="2" className="min-w-0 flex-1">
        <FolderIcon size={16} className="shrink-0 text-(--gray-12)" />
        <Text
          className="min-w-0 max-w-full truncate text-left font-medium text-(--gray-12)"
          title={displayValue || undefined}
        >
          {isOpening ? "Opening..." : displayValue || placeholder}
        </Text>
      </Flex>
      {isOpening ? (
        <CircleNotch
          size={14}
          className="shrink-0 animate-spin text-(--gray-9)"
        />
      ) : (
        <CaretDown size={14} className="shrink-0 text-(--gray-9)" />
      )}
    </>
  );

  const compactContent = (
    <>
      <FolderIcon size={14} weight="regular" className="shrink-0" />
      <span className="max-w-[120px] truncate">
        {isOpening ? "Opening..." : displayValue || placeholder}
      </span>
      {isOpening ? (
        <CircleNotch size={10} className="animate-spin text-muted-foreground" />
      ) : (
        <CaretDown size={10} weight="bold" className="text-muted-foreground" />
      )}
    </>
  );

  if (recentFolders.length === 0) {
    return isField ? (
      <button
        type="button"
        onClick={handleOpenFilePicker}
        className={FIELD_TRIGGER_CLASS}
        disabled={isOpening}
        aria-busy={isOpening}
      >
        {fieldContent}
      </button>
    ) : (
      <Button
        variant="outline"
        size="sm"
        aria-label="Folder"
        onClick={handleOpenFilePicker}
        disabled={isOpening}
        aria-busy={isOpening}
      >
        {compactContent}
      </Button>
    );
  }

  return (
    <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
      <DropdownMenuTrigger
        render={
          isField ? (
            <button type="button" className={FIELD_TRIGGER_CLASS}>
              {fieldContent}
            </button>
          ) : (
            <Button variant="outline" size="sm" aria-label="Folder">
              {compactContent}
            </Button>
          )
        }
      />
      <DropdownMenuContent
        anchor={anchor}
        align="start"
        side="bottom"
        sideOffset={isField ? 4 : 6}
        className={
          isField
            ? "w-(--anchor-width) min-w-(--anchor-width) max-w-(--anchor-width)"
            : "min-w-[200px]"
        }
      >
        <MenuLabel>Recent</MenuLabel>
        {folderRows.map(({ folder, isWorktree, indented }, index) => {
          const branch = branchQueries[index]?.data ?? null;
          return (
            <DropdownMenuItem
              key={folder.id}
              onClick={() => handleSelect(folder.path)}
              className={indented ? "group pl-6" : "group"}
            >
              {isWorktree ? (
                <GitFork size={12} className="shrink-0" />
              ) : (
                <GitBranch size={12} className="shrink-0" />
              )}
              <span
                className="min-w-0 flex-1 truncate text-left"
                title={branch ? `${folder.path} — on ${branch}` : folder.path}
              >
                {folder.name}
                {branch ? (
                  <span className="ml-1 text-muted-foreground">· {branch}</span>
                ) : null}
              </span>
              <button
                type="button"
                aria-label={`Remove ${folder.name} from recents`}
                className="-mr-1 ml-1 shrink-0 rounded p-0.5 text-(--gray-9) opacity-0 hover:bg-(--gray-4) hover:text-(--gray-12) focus-visible:opacity-100 group-hover:opacity-100"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  setMenuOpen(false);
                  setPendingRemoval({
                    id: folder.id,
                    name: folder.name,
                    path: folder.path,
                  });
                }}
              >
                <X size={12} />
              </button>
            </DropdownMenuItem>
          );
        })}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={handleOpenFilePicker}>
          <FolderOpen size={12} className="shrink-0" />
          <span className="whitespace-nowrap">Open folder...</span>
        </DropdownMenuItem>
      </DropdownMenuContent>

      <AlertDialog
        open={pendingRemoval !== null}
        onOpenChange={(open) => {
          if (!open && !isRemoving) setPendingRemoval(null);
        }}
      >
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Remove folder</AlertDialogTitle>
            <AlertDialogDescription>
              "{pendingRemoval?.name}" will be removed from PostHog, including
              all of its tasks and their workspaces. This can't be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={<Button variant="outline">Cancel</Button>}
            />
            <Button
              variant="destructive"
              loading={isRemoving}
              onClick={() => void handleConfirmRemoval()}
            >
              Remove
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </DropdownMenu>
  );
}
