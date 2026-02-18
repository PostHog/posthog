import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { sidePanelStateLogic } from '../sidePanelStateLogic'

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
}: SidePanelPaneHeaderProps): JSX.Element {
    const { modalMode } = useValues(sidePanelStateLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    return (
        <header
            className={cn(
                'border-b shrink-0 flex items-center justify-end',
                !modalMode ? 'sticky top-0 z-10 bg-surface-secondary p-1 h-10' : 'pb-2 mt-2 mx-3',
                isRemovingSidePanelFlag &&
                    'sticky top-0 h-[40px] bg-primary border-b-0 py-0 px-2 pb-px rounded justify-between m-0 mb-5 z-60 border',
                className
            )}
        >
            {title ? (
                <h3
                    className={cn('flex-1 flex items-center gap-1 font-semibold mb-0 truncate', {
                        'text-sm px-2': !modalMode,
                        'pr-1 flex-none pl-2': isRemovingSidePanelFlag,
                    })}
                >
                    {title}
                </h3>
            ) : null}

            {children}

            {isRemovingSidePanelFlag && (
                <>
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
                </>
            )}

            {!isRemovingSidePanelFlag && (
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
            )}
        </header>
    )
}
