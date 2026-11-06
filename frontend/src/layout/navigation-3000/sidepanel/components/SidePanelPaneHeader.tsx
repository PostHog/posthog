import { useActions } from 'kea'
import { createContext, useContext } from 'react'

import { IconX } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { sidePanelStateLogic } from '../sidePanelStateLogic'

/** True inside the Today context panel, whose own header already shows the tab title and a close button. */
export const SidePanelPaneHeaderHiddenContext = createContext(false)

export type SidePanelPaneHeaderProps = {
    title?: string | JSX.Element
    children?: React.ReactNode
    className?: string
    onClose?: () => void
    showCloseButton?: boolean
}

export function SidePanelPaneHeader({
    children,
    title,
    className,
    onClose,
    showCloseButton = false,
}: SidePanelPaneHeaderProps): JSX.Element | null {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const hidden = useContext(SidePanelPaneHeaderHiddenContext)

    if (hidden) {
        return children ? (
            <div className={cn('flex shrink-0 items-center gap-1 px-2 py-1', className)}>{children}</div>
        ) : null
    }

    return (
        <header
            className={cn(
                'scene-panel-pane-header border-b shrink-0 flex items-center justify-end',
                'sticky top-0 h-[40px] bg-primary border-b-0 py-0 px-2 pb-px rounded justify-between m-0 mb-5 z-60 border border-primary/30',
                className
            )}
        >
            {title ? (
                <h3 className="flex items-center gap-1 font-semibold mb-0 truncate pr-1 pl-2 flex-none text-sm">
                    {title}
                </h3>
            ) : null}

            {children}

            {showCloseButton && (
                <ButtonPrimitive
                    onClick={() => {
                        closeSidePanel()
                        onClose?.()
                    }}
                >
                    <IconX className="text-tertiary size-3 group-hover:text-primary z-10" />
                </ButtonPrimitive>
            )}
        </header>
    )
}
