import { LemonButton } from '@posthog/lemon-ui'

import { EventFilterForm } from 'scenes/data-pipelines/event-filtering/EventFilterForm'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { urls } from 'scenes/urls'

import { TransformationsFlowDisabledDetails } from './TransformationsFlowDisabledDetails'
import { TransformationsFlowTransformationDetails } from './TransformationsFlowTransformationDetails'
import { FlowStep } from './transformationsFlowUtils'

export function TransformationsFlowStepDetails({ step }: { step: FlowStep }): JSX.Element {
    switch (step.kind) {
        case 'capture':
            return (
                <p className="m-0">
                    PostHog receives events from your SDKs and the capture API. Each event then goes through the steps
                    below, from top to bottom.
                </p>
            )
        case 'event_filtering':
            return (
                <div className="flex flex-col gap-3">
                    <EventFilterForm />
                    <div>
                        <LemonButton size="small" type="tertiary" to={urls.eventFiltering()}>
                            Open full page
                        </LemonButton>
                    </div>
                </div>
            )
        case 'transformation':
            return step.hogFunction && step.position ? (
                <TransformationsFlowTransformationDetails hogFunction={step.hogFunction} position={step.position} />
            ) : (
                <p className="m-0">This transformation is not available. Refresh the page and try again.</p>
            )
        case 'disabled_transformation':
            return step.hogFunction ? (
                <TransformationsFlowDisabledDetails hogFunction={step.hogFunction} />
            ) : (
                <p className="m-0">This transformation is not available. Refresh the page and try again.</p>
            )
        case 'disabled_label':
            return <></>
        case 'add':
            return (
                <div className="flex flex-col gap-2">
                    <p className="m-0">
                        Transformations change or drop events before PostHog stores them. A new transformation runs
                        after your current ones. You can change its position after you save it.
                    </p>
                    <HogFunctionTemplateList type="transformation" hideFeedback />
                </div>
            )
        case 'person_processing':
            return (
                <p className="m-0">
                    After your transformations, PostHog creates or updates the person and groups for the event. This
                    step uses the event that your transformations return, so it also uses the properties that they
                    change.
                </p>
            )
        case 'stored':
            return (
                <p className="m-0">
                    PostHog writes the event to its database. You can then use it in insights, session replays, and
                    destinations. Destinations get the event with the changes from your transformations.
                </p>
            )
    }
}
