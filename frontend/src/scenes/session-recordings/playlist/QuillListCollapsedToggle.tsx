import { IconSidebarClose } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function QuillListCollapsedToggle({ onExpand }: { onExpand: () => void }): JSX.Element {
    return (
        <div
            data-quill
            className="flex items-start justify-center h-full w-full pt-2 pr-1 cursor-pointer"
            onClick={onExpand}
            data-attr="expand-playlist"
        >
            <Button
                size="icon-xs"
                tooltip="Expand playlist"
                aria-label="Expand playlist"
                data-attr="list-toggle-collapse"
            >
                <IconSidebarClose />
            </Button>
        </div>
    )
}
