import { IconSidebarClose } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export function ListCollapsedToggle({ onExpand }: { onExpand: () => void }): JSX.Element {
    return (
        <div
            className="flex items-start justify-center h-full w-full pt-2 pr-1 cursor-pointer"
            onClick={onExpand}
            data-attr="expand-playlist"
        >
            <LemonButton
                data-attr="list-toggle-collapse"
                icon={<IconSidebarClose />}
                tooltip="Expand playlist"
                size="xsmall"
                noPadding
            />
        </div>
    )
}
