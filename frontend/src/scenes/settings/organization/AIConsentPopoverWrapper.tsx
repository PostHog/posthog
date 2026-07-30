import { useActions, useAsyncActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useState } from 'react'

import { IconArrowRight, IconCheck, IconLock } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps, Tooltip } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'

import { getExternalAIProvidersTooltipTitle, openAIConsentLegalDialog } from './aiConsentCopy'
import { aiConsentLogic } from './aiConsentLogic'

export function AIConsentPopoverContent({
    onApprove,
    onDismiss,
    approvalDisabledReason,
    hideTrainingDisclaimer,
}: {
    onApprove: () => void
    onDismiss: () => void
    approvalDisabledReason: string | null
    /** Omit the "won't be used for training third-party models" line where it doesn't apply. */
    hideTrainingDisclaimer?: boolean
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
                .{!hideTrainingDisclaimer && <i> Your data won't be used for training third-party models.</i>}
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

function AIAccessRequestPopoverContent(): JSX.Element {
    const { requestingAiAccess, aiAccessRequested } = useValues(aiConsentLogic)
    const { requestAiAccess } = useActions(aiConsentLogic)

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

export function AIConsentPopoverWrapper({
    hidden,
    children,
    ignoreDismissal,
    onApprove,
    onDismiss,
    hideTrainingDisclaimer,
    ...popoverProps
}: Pick<PopoverProps, 'placement' | 'fallbackPlacements' | 'middleware' | 'showArrow'> & {
    children: JSX.Element
    hidden?: boolean
    /** Always show popover regardless of prior dismissal. */
    ignoreDismissal?: boolean
    onApprove?: () => void
    onDismiss?: () => void
    /** Passed through to AIConsentPopoverContent. */
    hideTrainingDisclaimer?: boolean
}): JSX.Element {
    const { acceptDataProcessing } = useAsyncActions(aiConsentLogic)
    const { dataProcessingApprovalDisabledReason, dataProcessingAccepted, dataProcessingDismissed } =
        useValues(aiConsentLogic)
    const { dismissDataProcessing } = useActions(aiConsentLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)
    // Hide the popover the moment consent is confirmed, without waiting for the organization PATCH to
    // land — otherwise the prompt is still up when the approved action re-runs, and the user is asked
    // to accept the same terms twice.
    const [approvalInFlight, setApprovalInFlight] = useState(false)

    const handleDismiss = (): void => {
        if (!ignoreDismissal) {
            dismissDataProcessing()
        }
        onDismiss?.()
    }

    const handleApprove = (): void => {
        setApprovalInFlight(true)
        void acceptDataProcessing()
            .then(() => {
                // The organization loader swallows request failures, so this resolving doesn't mean
                // the consent saved — check the value it would have set.
                if (!aiConsentLogic.values.dataProcessingAccepted) {
                    throw new Error('Organization AI data processing consent was not saved')
                }
                onApprove?.()
            })
            .catch((error) => {
                // Consent didn't actually save, so put the prompt back rather than leaving the user
                // believing they approved.
                setApprovalInFlight(false)
                posthog.captureException(error)
                lemonToast.error("Couldn't save your approval. Please try again.")
            })
    }

    return (
        <Popover
            overlay={
                isAdminOrOwner ? (
                    <AIConsentPopoverContent
                        approvalDisabledReason={dataProcessingApprovalDisabledReason}
                        hideTrainingDisclaimer={hideTrainingDisclaimer}
                        onApprove={handleApprove}
                        onDismiss={handleDismiss}
                    />
                ) : (
                    <AIAccessRequestPopoverContent />
                )
            }
            style={{ zIndex: 'var(--z-modal)' }} // Don't show above the re-authentication modal
            visible={
                !hidden && !dataProcessingAccepted && !approvalInFlight && (ignoreDismissal || !dataProcessingDismissed)
            }
            onClickOutside={handleDismiss}
            {...popoverProps}
        >
            {children}
        </Popover>
    )
}
