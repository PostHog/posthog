import { router } from 'kea-router'

import { IconEllipsis, IconRewindPlay } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { newInternalTab } from 'lib/utils/newInternalTab'

import { type VariantActionsMenuProps, useVariantActions } from './useVariantActions'

export function QuillVariantActionsMenu(props: VariantActionsMenuProps): JSX.Element {
    const { trackMenuOpened, recordings, sqlActions } = useVariantActions(props)
    const label = `Actions for ${props.variantKey}`

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                if (open) {
                    trackMenuOpened()
                }
            }}
        >
            <DropdownMenuTrigger
                render={
                    <Button size="icon-xs" aria-label={label} tooltip={label} data-attr="experiment-variant-actions" />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuGroup>
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger data-attr="experiment-variant-menu-recordings">
                            <IconRewindPlay />
                            View recordings
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            {recordings.map((recording) => (
                                <DropdownMenuItem
                                    key={recording.key}
                                    tooltip={recording.tooltip}
                                    disabledReason={recording.disabledReason}
                                    data-attr={recording.dataAttr}
                                    onClick={() => {
                                        recording.onClick()
                                        router.actions.push(recording.url)
                                    }}
                                >
                                    {recording.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    {sqlActions.map((action) => (
                        <DropdownMenuItem
                            key={action.key}
                            disabledReason={action.disabledReason}
                            data-attr={action.dataAttr}
                            onClick={() => {
                                action.onClick()
                                if (action.newTabUrl) {
                                    newInternalTab(action.newTabUrl)
                                }
                            }}
                        >
                            {action.icon}
                            {action.label}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
