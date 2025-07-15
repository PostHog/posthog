import { IconArrowRight, IconLock } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps, Tooltip } from '@posthog/lemon-ui'
import { useAsyncActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
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
                        Max needs your approval to potentially process
                        <br />
                        identifying user data using{' '}
                        <Tooltip
                            title={`As of ${dayjs().format(
                                'MMMM YYYY'
                            )}: OpenAI for core analysis, Perplexity for fetching product information`}
                        >
                            <dfn>external AI services</dfn>
                        </Tooltip>{' '}
                        <br />
                        <em>Your data won't be used for training models.</em>
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
