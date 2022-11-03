import { useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import {
    IS_TECHNICAL,
    IS_NOT_TECHNICAL,
    IS_TECHNICAL_SUBTEXT,
    IS_NOT_TECHNICAL_SUBTEXT,
} from 'scenes/ingestion/constants'
import { LemonButtonWithSideAction } from 'lib/components/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/components/LemonDivider'
import { IconChevronRight } from 'lib/components/icons'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function InviteTeamPanel(): JSX.Element {
    const { setTechnical } = useActions(ingestionLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)

    return (
        <div>
            <h1 className="ingestion-title">Welcome to PostHog</h1>
            <p>
                PostHog collects events from your website, mobile apps, backend, and more. To get started, we'll need to
                add a code snippet to your product.
            </p>
            <LemonDivider thick dashed className="my-6" />
            <div className="flex flex-col mb-6">
                <LemonButtonWithSideAction
                    onClick={() => setTechnical(true)}
                    fullWidth
                    size="large"
                    className="mb-4"
                    type="primary"
                    sideAction={{
                        icon: <IconChevronRight />,
                    }}
                >
                    <div className="mt-4 mb-0">
                        <p className="mb-2">{IS_TECHNICAL}</p>
                        <p className="font-normal text-xs">{IS_TECHNICAL_SUBTEXT}</p>
                    </div>
                </LemonButtonWithSideAction>
                <LemonButtonWithSideAction
                    onClick={() => {
                        setTechnical(false)
                        showInviteModal()
                        reportInviteMembersButtonClicked()
                    }}
                    fullWidth
                    size="large"
                    className="mb-4"
                    type="secondary"
                    sideAction={{
                        icon: <IconChevronRight />,
                    }}
                >
                    <div className="mt-4 mb-0">
                        <p className="mb-2">{IS_NOT_TECHNICAL}</p>
                        <p className="font-normal text-xs">{IS_NOT_TECHNICAL_SUBTEXT}</p>
                    </div>
                </LemonButtonWithSideAction>
            </div>
        </div>
    )
}
