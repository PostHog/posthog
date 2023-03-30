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
            // onClose()
        },
        []
    )

    return (
        <div className="ml-4 -mr-4 pt-0 p-8 AutomationStepConfig" ref={containerRef}>
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
