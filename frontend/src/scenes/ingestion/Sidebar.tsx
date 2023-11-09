import { ingestionLogic } from './ingestionLogic'
import { useActions, useValues } from 'kea'
import './IngestionWizard.scss'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { IconArticle, IconQuestionAnswer } from 'lib/lemon-ui/icons'
import { HelpType } from '~/types'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { organizationLogic } from 'scenes/organizationLogic'
import { Link } from '@posthog/lemon-ui'

const HELP_UTM_TAGS = '?utm_medium=in-product-onboarding&utm_campaign=help-button-sidebar'

export function Sidebar(): JSX.Element {
    const { currentStep, sidebarSteps, isProjectSwitcherShown } = useValues(ingestionLogic)
    const { sidebarStepClick, toggleProjectSwitcher, hideProjectSwitcher } = useActions(ingestionLogic)
    const { reportIngestionHelpClicked, reportIngestionSidebarButtonClicked } = useActions(eventUsageLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const currentIndex = sidebarSteps.findIndex((x) => x === currentStep)

    return (
        <div className="bg-bg-light flex flex-col relative items-center w-60">
            <div className="flex flex-col justify-between h-full p-4 fixed w-60 pb-20">
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
                    {currentOrganization?.teams && currentOrganization.teams.length > 1 && (
                        <>
                            <LemonButtonWithDropdown
                                icon={<Lettermark name={currentOrganization.name} />}
                                onClick={() => toggleProjectSwitcher()}
                                dropdown={{
                                    visible: isProjectSwitcherShown,
                                    onClickOutside: hideProjectSwitcher,
                                    overlay: <ProjectSwitcherOverlay />,
                                    actionable: true,
                                    placement: 'top-end',
                                }}
                                type="secondary"
                                fullWidth
                            >
                                <span className="text-muted">Switch project</span>
                            </LemonButtonWithDropdown>
                            <LemonDivider thick dashed className="my-6" />
                        </>
                    )}
                    <div className="IngestionSidebar__help">
                        <Link to={`https://posthog.com/slack${HELP_UTM_TAGS}`} target="_blank">
                            <LemonButton
                                icon={<IconQuestionAnswer />}
                                fullWidth
                                onClick={() => {
                                    reportIngestionHelpClicked(HelpType.Slack)
                                }}
                            >
                                Get support on Slack
                            </LemonButton>
                        </Link>
                        <Link
                            to={`https://posthog.com/docs/integrate/ingest-live-data${HELP_UTM_TAGS}`}
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
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    )
}
