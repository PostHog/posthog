import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { ingestionLogicV2, INGESTION_STEPS } from '../ingestionLogicV2'
import './Panels.scss'
import { IconArrowLeft, IconChevronRight } from 'lib/components/icons'
import { IngestionInviteMembersButton } from '../IngestionInviteMembersButton'
import { teamLogic } from 'scenes/teamLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

const DEMO_TEAM_NAME: string = 'Hedgebox'

export function PanelFooter(): JSX.Element {
    const { next } = useActions(ingestionLogicV2)

    return (
        <div className="panel-footer">
            <LemonDivider thick dashed className="my-6" />
            <div>
                <LemonButton
                    type="primary"
                    size="large"
                    fullWidth
                    center
                    className="mb-2"
                    onClick={() => next({ readyToVerify: true })}
                >
                    Continue
                </LemonButton>
                <IngestionInviteMembersButton />
            </div>
        </div>
    )
}

export function PanelHeader(): JSX.Element | null {
    const { isSmallScreen, previousStep, currentStep, hasInvitedMembers } = useValues(ingestionLogicV2)
    const { onBack } = useActions(ingestionLogicV2)

    // no back buttons on the Getting Started step
    // but only if it's not the MembersInvited panel
    // (since they'd want to be able to go back from there)
    if (currentStep === INGESTION_STEPS.START && !hasInvitedMembers) {
        return null
    }

    return (
        <div className="flex items-center mb-2" data-attr="wizard-step-counter">
            <LemonButton type="tertiary" status="primary" onClick={onBack} icon={<IconArrowLeft />} size="small">
                {isSmallScreen
                    ? ''
                    : // If we're on the MembersInvited panel, they "go back" to
                    // the Get Started step, even though it's technically the same step
                    currentStep === INGESTION_STEPS.START && hasInvitedMembers
                    ? currentStep
                    : previousStep}
            </LemonButton>
        </div>
    )
}

export function DemoProjectButton({ text, subtext }: { text: string; subtext?: string }): JSX.Element {
    const { next } = useActions(ingestionLogicV2)
    const { createTeam } = useActions(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { updateCurrentTeam } = useActions(userLogic)
    const { reportIngestionTryWithDemoDataClicked, reportProjectCreationSubmitted } = useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.ONBOARDING_V2_DEMO] !== 'test') {
        return <></>
    }
    return (
        <LemonButton
            onClick={() => {
                // If the current org has a demo team, just navigate there
                if (currentOrganization?.teams && currentOrganization.teams.filter((team) => team.is_demo).length > 0) {
                    updateCurrentTeam(currentOrganization.teams.filter((team) => team.is_demo)[0].id)
                } else {
                    // Create a new demo team
                    createTeam({ name: DEMO_TEAM_NAME, is_demo: true })
                    next({ isTechnicalUser: false, generatingDemoData: true })
                    reportProjectCreationSubmitted(
                        currentOrganization?.teams ? currentOrganization.teams.length : 0,
                        DEMO_TEAM_NAME.length
                    )
                }
                reportIngestionTryWithDemoDataClicked()
            }}
            fullWidth
            size="large"
            className="ingestion-view-demo-data mb-4"
            type="secondary"
            sideIcon={<IconChevronRight />}
        >
            <div className="mt-4 mb-0">
                <p className="mb-0">
                    {currentOrganization?.teams && currentOrganization.teams.filter((team) => team.is_demo).length > 0
                        ? 'Explore the demo project'
                        : text}
                </p>
                {subtext ? <p className="font-normal text-xs mt-2">{subtext}</p> : null}
            </div>
        </LemonButton>
    )
}
