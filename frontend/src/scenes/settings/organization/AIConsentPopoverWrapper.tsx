import { useAsyncActions, useValues } from 'kea'

import { IconArrowRight, IconLock } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
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
                <div className="flex flex-col m-1.5">
                    <p className="font-medium text-pretty mb-0">
                        PostHog AI needs your approval to potentially process
                        <br />
                        identifying user data with{' '}
                        <Tooltip title={`As of ${dayjs().format('MMMM YYYY')}: OpenAI`}>
                            <dfn>external AI providers</dfn>
                        </Tooltip>
                        .<br />
                        <i>Your data won't be used for training models.</i>
                    </p>
                    <p className="text-muted text-xs leading-relaxed mb-2">
                        If your org requires a Data Processing Agreement (DPA)
                        <br />
                        for compliance (and your existing DPA doesn't already
                        <br />
                        cover AI subprocessors),{' '}
                        <Link to="https://posthog.com/dpa" target="_blank">
                            you can get a fresh DPA here
                        </Link>
                        .
                    </p>
                    <div className="flex gap-1.5 self-end">
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
                            ref={(el) => {
                                el?.focus() // Auto-focus the button when the popover is opened, so that you just hit enter to approve
                            }}
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
