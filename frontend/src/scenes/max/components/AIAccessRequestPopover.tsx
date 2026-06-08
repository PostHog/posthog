import { useActions, useValues } from 'kea'

import { IconArrowRight, IconCheck } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps } from '@posthog/lemon-ui'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

export function AIAccessRequestPopoverContent(): JSX.Element {
    const { requestingAiAccess, aiAccessRequested } = useValues(maxGlobalLogic)
    const { requestAiAccess } = useActions(maxGlobalLogic)

    return (
        <div className="flex flex-col gap-2 m-1.5 max-w-prose">
            <p className="font-medium text-pretty">
                PostHog AI access has not been enabled for this organization. You can request access from an
                organization owner or admin.
            </p>
            <div className="flex self-end">
                <LemonButton
                    data-attr="ai-access-request"
                    type="primary"
                    size="xsmall"
                    onClick={() => requestAiAccess()}
                    loading={requestingAiAccess}
                    disabledReason={aiAccessRequested ? 'Your request has been sent' : undefined}
                    sideIcon={aiAccessRequested ? <IconCheck /> : <IconArrowRight />}
                >
                    {aiAccessRequested ? 'Request sent' : 'Request access'}
                </LemonButton>
            </div>
        </div>
    )
}

export function AIAccessRequestPopoverWrapper({
    hidden,
    children,
    onDismiss,
    ...popoverProps
}: Pick<PopoverProps, 'placement' | 'fallbackPlacements' | 'middleware' | 'showArrow'> & {
    children: JSX.Element
    hidden?: boolean
    onDismiss?: () => void
}): JSX.Element {
    return (
        <Popover
            overlay={<AIAccessRequestPopoverContent />}
            style={{ zIndex: 'var(--z-modal)' }} // Don't show above the re-authentication modal
            visible={!hidden}
            onClickOutside={onDismiss}
            {...popoverProps}
        >
            {children}
        </Popover>
    )
}
