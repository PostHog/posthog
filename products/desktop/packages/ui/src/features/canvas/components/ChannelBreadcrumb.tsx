import { HashIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { HeaderTitleEditor } from "@posthog/ui/features/task-detail/HeaderTitleEditor";
import { Flex, Text } from "@radix-ui/themes";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useState } from "react";

interface ChannelBreadcrumbProps {
  /** The channel (root) segment label. */
  channelName: string;
  /**
   * When provided, the "# channel" segment links to the channel home, like the
   * sidebar channel row and the channel-view header.
   */
  channelId?: string;
  /** Optional leading icon for the leaf segment (e.g. a canvas's tier icon). */
  leafIcon?: ReactNode;
  /** The trailing (current page) segment label. */
  leafLabel: string;
  editScopeKey?: string;
  /**
   * When provided, the leaf becomes inline-editable: double-click to rename,
   * Enter or blur to submit, Escape to cancel. Receives the trimmed new value.
   */
  onRename?: (next: string) => void;
  /** Right-aligned slot pushed to the far end of the bar (e.g. an opener). */
  trailing?: ReactNode;
}

// "# channel / leaf" header breadcrumb shared across channel scenes (CONTEXT.md,
// new + existing tasks, canvases). The leaf can carry a tier icon and, when
// onRename is given, edits inline using the same editor as task titles. When
// channelId is given, the "# channel" segment links back to the channel home.
export function ChannelBreadcrumb({
  channelName,
  channelId,
  leafIcon,
  leafLabel,
  editScopeKey,
  onRename,
  trailing,
}: ChannelBreadcrumbProps) {
  const currentEditScope = editScopeKey ?? leafLabel;
  const [editingScope, setEditingScope] = useState<string | null>(null);
  const editing = editingScope === currentEditScope;
  const navigate = useNavigate();

  const channelSegment = (
    <>
      <HashIcon size={12} className="mt-px shrink-0 text-muted-foreground/80" />
      <Text
        className="min-w-0 truncate whitespace-nowrap font-medium text-[13px]"
        title={channelName}
      >
        {channelName}
      </Text>
    </>
  );

  return (
    <Flex align="center" justify="between" gap="2" className="w-full min-w-0">
      <Flex align="center" gap="1" className="min-w-0">
        {channelId ? (
          <Button
            type="button"
            onClick={() =>
              void navigate({
                to: "/website/$channelId",
                params: { channelId },
              })
            }
            size="sm"
            className="no-drag"
          >
            {channelSegment}
          </Button>
        ) : (
          <div className="flex items-center gap-1">{channelSegment}</div>
        )}
        <Text className="shrink-0 text-[13px] text-muted-foreground/20">/</Text>
        <div className="flex items-center gap-1.5">
          {leafIcon && (
            <span className="mt-px flex shrink-0 text-primary">{leafIcon}</span>
          )}
          {editing && onRename ? (
            <HeaderTitleEditor
              initialTitle={leafLabel}
              onSubmit={(next) => {
                setEditingScope(null);
                onRename(next);
              }}
              onCancel={() => setEditingScope(null)}
            />
          ) : (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Text
                    truncate
                    className="no-drag min-w-0 whitespace-nowrap text-[13px]"
                    onDoubleClick={
                      onRename
                        ? () => setEditingScope(currentEditScope)
                        : undefined
                    }
                  />
                }
              >
                {leafLabel}
              </TooltipTrigger>
              <TooltipContent>{leafLabel}</TooltipContent>
            </Tooltip>
          )}
        </div>
      </Flex>
      {trailing}
    </Flex>
  );
}
