import { ingestionLogic } from './ingestionLogic'
import { useActions, useValues } from 'kea'
import './IngestionWizard.scss'
import { InviteMembersButton } from '~/layout/navigation/TopBar/SitePopover'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconArticle, IconQuestionAnswer } from 'lib/lemon-ui/icons'
import { HelpType } from '~/types'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

const HELP_UTM_TAGS = '?utm_medium=in-product-onboarding&utm_campaign=help-button-sidebar'

export function Sidebar(): JSX.Element {
    const { currentStep, sidebarSteps } = useValues(ingestionLogic)
    const { sidebarStepClick } = useActions(ingestionLogic)
    const { reportIngestionHelpClicked, reportIngestionSidebarButtonClicked } = useActions(eventUsageLogic)

    const currentIndex = sidebarSteps.findIndex((x) => x === currentStep)

    return (
        <div className="IngestionSidebar">
            <div className="IngestionSidebar__content">
                <div className="IngestionSidebar__steps">
                    {sidebarSteps.map((step: string, index: number) => (
                        <LemonButton
                            key={index}
                            active={currentStep === step}
                            disabled={index > currentIndex}
                            onClick={() => {
                                sidebarStepClick(step)
                                reportIngestionSidebarButtonClicked(step)
                            }}
                        >
                            {step}
                        </LemonButton>
                    ))}
                </div>
                <div className="IngestionSidebar__bottom">
                    <InviteMembersButton center={true} type="primary" />
                    <LemonDivider thick dashed className="my-6" />
                    <div className="IngestionSidebar__help">
                        <a href={`https://posthog.com/slack${HELP_UTM_TAGS}`} rel="noopener" target="_blank">
                            <LemonButton
                                icon={<IconQuestionAnswer />}
                                fullWidth
                                onClick={() => {
                                    reportIngestionHelpClicked(HelpType.Slack)
                                }}
                            >
                                Get support on Slack
                            </LemonButton>
                        </a>
                        <a
                            href={`https://posthog.com/docs/integrate/ingest-live-data${HELP_UTM_TAGS}`}
                            rel="noopener"
                            target="_blank"
                            className="mt-2"
                        >
                            <LemonButton
                                icon={<IconArticle />}
                                fullWidth
                                onClick={() => {
                                    reportIngestionHelpClicked(HelpType.Docs)
                                }}
                            >
                                Read our documentation
                            </LemonButton>
                        </a>
                    </div>
                </div>
            </div>
        </div>
    )
}
