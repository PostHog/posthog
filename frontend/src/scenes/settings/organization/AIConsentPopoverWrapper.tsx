import { IconLock } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps, Tooltip, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

export function AIConsentPopoverWrapper({
    children,
    onDismiss,
    ...popoverProps
}: Pick<PopoverProps, 'placement' | 'fallbackPlacements' | 'middleware' | 'showArrow'> & {
    children: JSX.Element
    onDismiss?: () => void
}): JSX.Element {
    const { acceptDataProcessing } = useActions(maxGlobalLogic)
    const { dataProcessingApprovalDisabledReason, dataProcessingAccepted } = useValues(maxGlobalLogic)

    const handleAcceptDataProcessing = (): void => {
        acceptDataProcessing()
    }

    const handleClickOutside = (): void => {
        onDismiss?.()
    }

    return (
        <Popover
            // Note: Sync the copy below with organization-ai-consent in SettingsMap.tsx
            overlay={
                <div className="m-1.5">
                    <p className="font-medium text-pretty mb-1.5">
                        Hi! I use{' '}
                        <Tooltip
                            title={`As of ${dayjs().format(
                                'MMMM YYYY'
                            )}: OpenAI for core analysis, Perplexity for fetching product information`}
                        >
                            <dfn>external AI services</dfn>
                        </Tooltip>
                        , which can mean identifying data is shared with these services. We recommend{' '}
                        <Link to="https://posthog.com/dpa" target="_blank" targetBlankIcon>
                            signing a DPA
                        </Link>{' '}
                        if needed, but data is never used for training models.
                    </p>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={handleAcceptDataProcessing}
                        sideIcon={dataProcessingApprovalDisabledReason ? <IconLock /> : undefined}
                        disabledReason={dataProcessingApprovalDisabledReason}
                        tooltip="You are approving this as an organization admin"
                        tooltipPlacement="bottom"
                    >
                        I allow AI-based analysis in this organization
                    </LemonButton>
                </div>
            }
            style={{ zIndex: 'var(--z-modal)' }} // Don't show above the re-authentication modal
            visible={!dataProcessingAccepted}
            onClickOutside={handleClickOutside}
            {...popoverProps}
        >
            {children}
        </Popover>
    )
}
