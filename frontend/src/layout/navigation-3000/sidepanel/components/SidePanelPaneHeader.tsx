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
}

export function SidePanelPaneHeader({ children, title, className, onClose }: SidePanelPaneHeaderProps): JSX.Element {
    const { modalMode } = useValues(sidePanelStateLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    return (
        <header
            className={cn(
                'border-b shrink-0 flex items-center justify-end',
                !modalMode ? 'sticky top-0 z-10 bg-surface-secondary p-1 h-10' : 'pb-2 mt-2 mx-3',
                isRemovingSidePanelFlag &&
                    'h-[var(--scene-layout-header-height)] bg-surface-tertiary border-b-0 py-0 px-2',
                className
            )}
        >
            {title ? (
                <h3
                    className={cn('flex-1 flex items-center gap-1 font-semibold mb-0 truncate', {
                        'text-sm px-2': !modalMode,
                    })}
                >
                    {title}
                </h3>
            ) : null}

            {children}

            {isRemovingSidePanelFlag ? (
                <ButtonPrimitive
                    onClick={() => {
                        closeSidePanel()
                        onClose?.()
                    }}
                    tooltip="Close side panel"
                    tooltipPlacement="bottom-end"
                    iconOnly
                    className="group"
                >
                    <IconX className="text-tertiary size-3 group-hover:text-primary z-10" />
                </ButtonPrimitive>
            ) : (
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
