import { Check, FolderOpen, FolderPlus } from "@phosphor-icons/react";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { useService } from "@posthog/di/react";
import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { useMemo } from "react";

interface AdditionalDirectoriesButtonProps {
  values: string[];
  onChange: (values: string[]) => void;
  primaryDirectory?: string | null;
  disabled?: boolean;
}

export function AdditionalDirectoriesButton({
  values,
  onChange,
  primaryDirectory,
  disabled,
}: AdditionalDirectoriesButtonProps) {
  const trpcClient = useHostTRPCClient();
  const log = useService<RootLogger>(ROOT_LOGGER);
  const { getFolderByPath, getRecentFolders, addFolder, updateLastAccessed } =
    useFolders();
  const count = values.length;
  const selected = useMemo(() => new Set(values), [values]);

  const folders = useMemo(() => {
    const recent = getRecentFolders().filter(
      (f) => f.path !== primaryDirectory,
    );
    const seen = new Set(recent.map((f) => f.path));
    for (const path of values) {
      if (seen.has(path)) continue;
      const folder = getFolderByPath(path);
      if (folder) {
        recent.push(folder);
        seen.add(path);
      }
    }
    return recent;
  }, [getRecentFolders, getFolderByPath, values, primaryDirectory]);

  const toggle = (path: string) => {
    if (selected.has(path)) {
      onChange(values.filter((p) => p !== path));
      return;
    }
    onChange([...values, path]);
    const folder = getFolderByPath(path);
    if (folder) updateLastAccessed(folder.id);
  };

  const handlePickNative = async () => {
    try {
      const selectedPath = await trpcClient.os.selectDirectory.query();
      if (!selectedPath) return;
      if (selectedPath === primaryDirectory) return;
      await addFolder(selectedPath);
      if (!selected.has(selectedPath)) {
        onChange([...values, selectedPath]);
      }
    } catch (error) {
      log.error("Failed to open directory picker", { error });
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            aria-label="Additional directories"
            disabled={disabled}
          >
            <FolderPlus size={14} weight="regular" className="shrink-0" />
            {count > 0 && (
              <span className="font-medium tabular-nums">+{count}</span>
            )}
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="min-w-[260px]"
      >
        {folders.length > 0 && (
          <>
            <MenuLabel>Additional directories</MenuLabel>
            {folders.map((folder) => {
              const isSelected = selected.has(folder.path);
              return (
                <DropdownMenuItem
                  key={folder.id}
                  closeOnClick={false}
                  onClick={() => toggle(folder.path)}
                >
                  <Check
                    size={12}
                    weight="bold"
                    className={`shrink-0 ${isSelected ? "" : "invisible"}`}
                  />
                  <span
                    className="min-w-0 flex-1 truncate text-left"
                    title={folder.path}
                  >
                    {folder.name}
                  </span>
                </DropdownMenuItem>
              );
            })}
            <DropdownMenuSeparator />
          </>
        )}

        <DropdownMenuItem onClick={handlePickNative}>
          <FolderOpen size={12} className="shrink-0" />
          <span className="whitespace-nowrap">Open folder...</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
