import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconClose } from 'lib/lemon-ui/icons'

import { sidePanelStateLogic } from '../sidePanelStateLogic'

export type SidePanelPaneHeaderProps = {
    title?: string | JSX.Element
    children?: React.ReactNode
}

export function SidePanelPaneHeader({ children, title }: SidePanelPaneHeaderProps): JSX.Element {
    const { modalMode } = useValues(sidePanelStateLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    return (
        <header
            className={clsx('border-b shrink-0 flex items-center justify-end gap-1', {
                'p-1 h-10': !modalMode,
                'pb-2 mt-2 mx-3': modalMode,
            })}
        >
            {title ? (
                <h3
                    className={clsx('flex-1 flex items-center gap-1 font-semibold mb-0 truncate', {
                        'text-base px-2': !modalMode,
                    })}
                >
                    {title}
                </h3>
            ) : null}
            {children}
            <Tooltip
                placement={modalMode ? 'top' : 'bottomRight'}
                title={modalMode ? 'Close' : 'Close this side panel'}
            >
                <LemonButton size="small" sideIcon={<IconClose />} onClick={() => closeSidePanel()} />
            </Tooltip>
        </header>
    )
}
