import { LemonButton } from '@posthog/lemon-ui'
import { IconClose } from 'lib/lemon-ui/icons'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { useRef } from 'react'

type AutomationStepSidebarProps = {
    onClose: () => void
    children: React.ReactNode
}

export function AutomationStepSidebar({ onClose, children }: AutomationStepSidebarProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)

    useOutsideClickHandler(
        containerRef,
        () => {
            console.debug('outside click')
            onClose()
        },
        []
    )

    return (
        <div className="w-full m-4 p-8 border bg-white AutomationStepConfig relative" ref={containerRef}>
            <LemonButton
                icon={<IconClose />}
                size="small"
                status="stealth"
                onClick={onClose}
                aria-label="close"
                className="closebutton"
            />
            {children}
        </div>
    )
}
