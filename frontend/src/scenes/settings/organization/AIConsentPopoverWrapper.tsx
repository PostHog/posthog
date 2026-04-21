import { useActions, useAsyncActions, useValues } from 'kea'

import { IconArrowRight, IconLock } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { AI_HIPAA_DISCLAIMER, ExternalAIProvidersTooltip } from './aiConsentCopy'

export function AIConsentPopoverContent({
    onApprove,
    onDismiss,
    approvalDisabledReason,
}: {
    onApprove: () => void
    onDismiss: () => void
    approvalDisabledReason: string | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2 m-1.5 max-w-sm">
            <p className="font-medium text-pretty">
                PostHog AI needs your approval to potentially process identifying user data with{' '}
                <ExternalAIProvidersTooltip>
                    <dfn>external AI providers</dfn>
                </ExternalAIProvidersTooltip>
                . <i>Your data won't be used for training models.</i>
            </p>
            <p className="text-muted text-xs leading-relaxed">
                If your org requires a Data Processing Agreement (DPA) for compliance (and your existing DPA doesn't
                already cover AI subprocessors),{' '}
                <Link to="https://posthog.com/dpa" target="_blank">
                    you can get a fresh DPA here
                </Link>
                .
            </p>
            <p className="text-muted text-xs leading-relaxed">{AI_HIPAA_DISCLAIMER}</p>
            <div className="flex gap-1.5 self-end">
                <LemonButton type="secondary" size="xsmall" onClick={onDismiss}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="xsmall"
                    onClick={onApprove}
                    sideIcon={approvalDisabledReason ? <IconLock /> : <IconArrowRight />}
                    disabledReason={approvalDisabledReason}
                    tooltip="You are approving this as an organization admin"
                    tooltipPlacement="bottom"
                    ref={(el) => {
                        el?.focus() // Auto-focus the button when the popover is opened, so that you just hit enter to approve
                    }}
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
