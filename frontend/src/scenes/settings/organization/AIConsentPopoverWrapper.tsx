import { IconLock } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

export function AIConsentPopoverWrapper({
    children,
    ...popoverProps
}: Pick<PopoverProps, 'placement' | 'fallbackPlacements' | 'middleware' | 'showArrow'> & {
    children: JSX.Element
}): JSX.Element {
    const { acceptDataProcessing } = useActions(maxGlobalLogic)
    const { dataProcessingApprovalDisabledReason, dataProcessingAccepted } = useValues(maxGlobalLogic)

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
                        </Tooltip>{' '}
                        for data analysis,
                        <br />
                        so that you can focus on building. This <em>can</em> include
                        <br />
                        identyifying data of your users, if you're capturing it.
                        <br />
                        <em>Your data won't be used for training models.</em>
                    </p>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => acceptDataProcessing()}
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
            {...popoverProps}
        >
            {children}
        </Popover>
    )
}
