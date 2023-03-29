import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import {
    GithubIcon,
    IconAction,
    IconApps,
    IconArticle,
    IconClose,
    IconCoffee,
    IconCohort,
    IconEvent,
    IconFlag,
    IconMonitor,
    IconPerson,
    IconSlack,
    IconWebhook,
} from 'lib/lemon-ui/icons'
import './AutomationStepConfig.scss'
import { automationStepConfigLogic } from './automationStepConfigLogic'

export function AutomationStepConfig(): JSX.Element {
    const { closeStepConfig } = useActions(automationStepConfigLogic)

    const eventSteps = [
        { label: 'Event sent', icon: <IconEvent /> },
        { label: 'Action triggered', icon: <IconAction /> },
    ]

    const delaySteps = [
        { label: 'Pause for', icon: <IconCoffee /> },
        { label: 'Pause until', icon: <IconCoffee /> },
    ]

    const destinationsSteps = [
        { label: 'Create a Github ticket', icon: <GithubIcon /> },
        { label: 'Set user property', icon: <IconPerson /> },
        { label: 'Add to cohort', icon: <IconCohort /> },
        { label: 'Add to feature flags', icon: <IconFlag /> },
        { label: 'Send a webhook', icon: <IconWebhook /> },
        { label: 'Send to slack', icon: <IconSlack /> },
        { label: 'Send to Zapier', icon: <IconApps /> },
        { label: 'Send an email', icon: <IconArticle /> },
        { label: 'In-app message', icon: <IconMonitor /> },
    ]
    return (
        <div className="w-full m-4 p-8 border bg-white AutomationStepConfig">
            {/* close button in the top right of the div using LemonButton */}
            <LemonButton
                icon={<IconClose />}
                size="small"
                status="stealth"
                onClick={closeStepConfig}
                aria-label="close"
            />
            <h1>New Step</h1>
            <LemonDivider />
            <h3>Sources</h3>
            <div className="StepChooser mb-4">
                {eventSteps.map((option, key) => (
                    <LemonButton type="secondary" icon={option.icon} key={key}>
                        {option.label}
                    </LemonButton>
                ))}
            </div>
            <LemonDivider />
            <h3>Delays</h3>
            <div className="StepChooser mb-4">
                {delaySteps.map((option, key) => (
                    <LemonButton type="secondary" icon={option.icon} key={key}>
                        {option.label}
                    </LemonButton>
                ))}
            </div>
            <LemonDivider />
            <h3>Destinations</h3>
            <div className="StepChooser mb-4">
                {destinationsSteps.map((option, key) => (
                    <LemonButton type="secondary" icon={option.icon} key={key}>
                        {option.label}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
