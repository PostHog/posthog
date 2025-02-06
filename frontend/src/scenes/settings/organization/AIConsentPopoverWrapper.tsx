import { IconLock } from '@posthog/icons'
import { LemonButton, Popover, PopoverProps } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

export function AIConsentPopoverWrapper({
    children,
    ...popoverProps
}: Pick<PopoverProps, 'placement' | 'middleware' | 'showArrow'> & { children: JSX.Element }): JSX.Element {
    const { acceptDataProcessing } = useActions(maxGlobalLogic)
    const { dataProcessingApprovalDisabledReason, dataProcessingAccepted } = useValues(maxGlobalLogic)

    return (
        <Popover
            overlay={
                <div className="m-1.5">
                    <p className="font-medium text-pretty mb-1.5">
                        Hi! I use OpenAI services to analyze your data,
                        <br />
                        so that you can focus on building. This <em>can</em> include
                        <br />
                        personal data of your users, if you're capturing it.
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
                        I allow OpenAI-based analysis in this organization
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
