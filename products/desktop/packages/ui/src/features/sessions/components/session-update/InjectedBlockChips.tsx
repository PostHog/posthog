import type { InjectedBlock } from "@posthog/core/editor/injectedBlocks";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { INJECTED_BLOCK_PRESENTATION } from "@posthog/ui/features/sessions/components/session-update/injectedBlocks";
import { MentionChip } from "@posthog/ui/features/sessions/components/session-update/parseFileMentions";

interface InjectedBlockChipsProps {
  blocks: InjectedBlock[];
  taskId?: string | null;
}

export function InjectedBlockChips({
  blocks,
  taskId,
}: InjectedBlockChipsProps) {
  const openInjectedBlockTab = usePanelLayoutStore(
    (s) => s.openInjectedBlockTab,
  );
  return (
    <>
      {blocks.map((block) => {
        const {
          icon: BlockIcon,
          label,
          tooltip,
          tab,
        } = INJECTED_BLOCK_PRESENTATION[block.kind];
        const text = label(block);
        return (
          <MentionChip
            key={block.kind}
            icon={<BlockIcon size={12} />}
            label={text}
            tooltip={tooltip}
            onClick={
              tab && taskId
                ? () => openInjectedBlockTab(taskId, { block, label: text })
                : undefined
            }
          />
        );
      })}
    </>
  );
}
