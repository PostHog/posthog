import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { sidePanelStateLogic } from '../sidePanelStateLogic'

export type SidePanelPaneHeaderProps = {
    title?: string | JSX.Element
    children?: React.ReactNode
    className?: string
    onClose?: () => void
}

export function SidePanelPaneHeader({ children, title, className, onClose }: SidePanelPaneHeaderProps): JSX.Element {
    const { modalMode } = useValues(sidePanelStateLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    return (
        <header
            className={clsx(
                'border-b shrink-0 flex items-center justify-end',
                !modalMode ? 'sticky top-0 z-10 bg-surface-secondary p-1 h-10' : 'pb-2 mt-2 mx-3',
                className
            )}
        >
            {title ? (
                <h3
                    className={clsx('flex-1 flex items-center gap-1 font-semibold mb-0 truncate', {
                        'text-sm px-2': !modalMode,
                    })}
                >
                    {title}
                </h3>
            ) : null}
            {children}
            <LemonButton
                size="small"
                sideIcon={<IconX />}
                onClick={() => {
                    closeSidePanel()
                    onClose?.()
                }}
                tooltip={modalMode ? 'Close' : 'Close this side panel'}
                tooltipPlacement={modalMode ? 'top' : 'bottom-end'}
            />
        </header>
    )
}
