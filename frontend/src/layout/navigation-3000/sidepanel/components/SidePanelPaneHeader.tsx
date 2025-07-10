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
                'flex shrink-0 items-center justify-end border-b',
                !modalMode ? 'bg-surface-secondary sticky top-0 z-10 h-10 p-1' : 'mx-3 mt-2 pb-2',
                className
            )}
        >
            {title ? (
                <h3
                    className={clsx('mb-0 flex flex-1 items-center gap-1 truncate font-semibold', {
                        'px-2 text-sm': !modalMode,
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
