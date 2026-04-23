import { useActions, useAsyncActions, useValues } from 'kea'
import { useCallback } from 'react'

import { IconArrowRight, IconLock } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps, Tooltip } from '@posthog/lemon-ui'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { getExternalAIProvidersTooltipTitle, openAIConsentLegalDialog } from './aiConsentCopy'

export function AIConsentPopoverContent({
    onApprove,
    onDismiss,
    approvalDisabledReason,
}: {
    onApprove: () => void
    onDismiss: () => void
    approvalDisabledReason: string | null
}): JSX.Element {
    const focusOnMount = useCallback((el: HTMLButtonElement | null) => {
        el?.focus()
    }, [])

    return (
        <div className="flex flex-col gap-2 m-1.5 max-w-prose">
            <p className="font-medium text-pretty">
                PostHog AI needs your approval to potentially process identifying user data with{' '}
                <Tooltip title={getExternalAIProvidersTooltipTitle()}>
                    <dfn>external AI providers</dfn>
                </Tooltip>
                . <i>Your data won't be used for training models.</i>
            </p>
            <div className="flex gap-1.5 self-end">
                <LemonButton data-attr="ai-consent-cancel" type="secondary" size="xsmall" onClick={onDismiss}>
                    Cancel
                </LemonButton>
                <LemonButton
                    data-attr="ai-consent-approve"
                    type="primary"
                    size="xsmall"
                    onClick={() => openAIConsentLegalDialog({ onConfirm: onApprove })}
                    sideIcon={approvalDisabledReason ? <IconLock /> : <IconArrowRight />}
                    disabledReason={approvalDisabledReason}
                    tooltip={approvalDisabledReason ? undefined : 'You are approving this as an organization admin'}
                    tooltipPlacement="bottom"
                    ref={focusOnMount}
                >
                    I allow AI analysis in this organization
                </LemonButton>
            </div>
        </div>
    )
}

export function AIConsentPopoverWrapper({
    hidden,
    children,
    ignoreDismissal,
    onApprove,
    onDismiss,
    ...popoverProps
}: Pick<PopoverProps, 'placement' | 'fallbackPlacements' | 'middleware' | 'showArrow'> & {
    children: JSX.Element
    hidden?: boolean
    /** Always show popover regardless of prior dismissal. */
    ignoreDismissal?: boolean
    onApprove?: () => void
    onDismiss?: () => void
}): JSX.Element {
    const { acceptDataProcessing } = useAsyncActions(maxGlobalLogic)
    const { dataProcessingApprovalDisabledReason, dataProcessingAccepted, dataProcessingDismissed } =
        useValues(maxGlobalLogic)
    const { dismissDataProcessing } = useActions(maxGlobalLogic)

    const handleDismiss = (): void => {
        if (!ignoreDismissal) {
            dismissDataProcessing()
        }
        onDismiss?.()
    }

    return (
        <Popover
            overlay={
                <AIConsentPopoverContent
                    approvalDisabledReason={dataProcessingApprovalDisabledReason}
                    onApprove={() =>
                        void acceptDataProcessing()
                            .then(() => onApprove?.())
                            .catch(console.error)
                    }
                    onDismiss={handleDismiss}
                />
            }
            style={{ zIndex: 'var(--z-modal)' }} // Don't show above the re-authentication modal
            visible={!hidden && !dataProcessingAccepted && (ignoreDismissal || !dataProcessingDismissed)}
            onClickOutside={handleDismiss}
            {...popoverProps}
        >
            {children}
        </Popover>
    )
}
