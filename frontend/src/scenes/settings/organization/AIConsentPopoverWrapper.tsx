import { IconArrowRight, IconLock } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps, Tooltip } from '@posthog/lemon-ui'
import { dayjs } from 'lib/dayjs'
import { useAsyncActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

export function AIConsentPopoverWrapper({
    hidden,
    children,
    onApprove,
    onDismiss,
    ...popoverProps
}: Pick<PopoverProps, 'placement' | 'fallbackPlacements' | 'middleware' | 'showArrow'> & {
    children: JSX.Element
    hidden?: boolean
    onApprove?: () => void
    onDismiss?: () => void
}): JSX.Element {
    const { acceptDataProcessing } = useAsyncActions(maxGlobalLogic)
    const { dataProcessingApprovalDisabledReason, dataProcessingAccepted } = useValues(maxGlobalLogic)

    const handleClickOutside = (): void => {
        onDismiss?.()
    }

    return (
        <Popover
            // Note: Sync the copy below with organization-ai-consent in SettingsMap.tsx
            overlay={
                <div className="flex flex-col items-end m-1.5">
                    <p className="font-medium text-pretty mb-1.5">
                        Max needs your approval to potentially process and share identifying data with{' '}
                        <Tooltip
                            title={`As of ${dayjs().format(
                                'MMMM YYYY'
                            )}: OpenAI for core analysis, Perplexity for fetching product information`}
                        >
                            <dfn>external AI providers</dfn>
                        </Tooltip>
                        .{' '}
                        <span className="text-muted-foreground">
                            If your organization requires a Data Processing Agreement (DPA) for GDPR compliance – and
                            your existing DPA doesn't already cover LLM subprocessors – you can request one at{' '}
                            <Link to="https://posthog.com/dpa" target="_blank">
                                https://posthog.com/dpa
                            </Link>
                            .
                        </span>
                    </p>
                    <div className="flex gap-1.5">
                        <LemonButton type="secondary" size="xsmall" onClick={onDismiss}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            onClick={() =>
                                void acceptDataProcessing()
                                    .then(() => onApprove?.())
                                    .catch(console.error)
                            }
                            sideIcon={dataProcessingApprovalDisabledReason ? <IconLock /> : <IconArrowRight />}
                            disabledReason={dataProcessingApprovalDisabledReason}
                            tooltip="You are approving this as an organization admin"
                            tooltipPlacement="bottom"
                        >
                            I allow AI analysis in this organization
                        </LemonButton>
                    </div>
                </div>
            }
            style={{ zIndex: 'var(--z-modal)' }} // Don't show above the re-authentication modal
            visible={!hidden && !dataProcessingAccepted}
            onClickOutside={handleClickOutside}
            {...popoverProps}
        >
            {children}
        </Popover>
    )
}
