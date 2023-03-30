import { LemonButton, LemonCollapse, LemonDivider, LemonInput, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PureField } from 'lib/forms/Field'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { FilterType, InsightType } from '~/types'
import './AutomationStepConfig.scss'
import { automationStepConfigLogic } from './automationStepConfigLogic'
import { AutomationStepSidebar } from './AutomationStepSidebar'
import { AutomationEventSourceStep } from '../schema'

export function WebhookDestinationConfig(): JSX.Element {
    const { activeStep, activeStepConfig, exampleEvent, previewPayload } = useValues(automationStepConfigLogic)
    const { updateActiveStep, setExampleEvent } = useActions(automationStepConfigLogic)

    console.log('activeStep', activeStep)
    return (
        <>
            <PureField label={'Destination url'}>
                <LemonInput
                    placeholder="Where do you want to send the payload?"
                    value={activeStep?.data?.url}
                    onChange={(url) => {
                        updateActiveStep(activeStep?.data?.id, { url })
                    }}
                />
            </PureField>
            <div className="mt-4" />
            <PureField label={'Payload'} className="max-w-160">
                <JSONEditorInput
                    defaultNumberOfLines={4}
                    value={activeStep?.data?.payload}
                    onChange={(payload) => {
                        updateActiveStep(activeStep?.data?.id, { payload })
                    }}
                />
            </PureField>
            <div className="mt-4" />
            <PureField label={'Preview'} className="max-w-160">
                <JSONEditorInput defaultNumberOfLines={4} value={JSON.stringify(previewPayload, null, 4)} readOnly />
                <LemonCollapse
                    panels={[
                        {
                            key: '1',
                            header: <span>Example event</span>,
                            content: (
                                <JSONEditorInput
                                    defaultNumberOfLines={4}
                                    value={exampleEvent}
                                    onChange={(val) => {
                                        setExampleEvent(val)
                                    }}
                                />
                            ),
                        },
                    ]}
                />
            </PureField>
            <div className="mt-4" />
        </>
    )
}

export function EventSentConfig(): JSX.Element {
    const { activeStep } = useValues(automationStepConfigLogic)
    const { updateActiveStep } = useActions(automationStepConfigLogic)

    if (activeStep === null) {
        throw new Error('activeStep should not be null')
    }

    return (
        <div className="mb-6">
            <div className="mb-2">
                <LemonLabel>Event filtering</LemonLabel>
                {/* <p className="text-sm text-muted">{variable.description}</p> */}
            </div>
            <div>
                <ActionFilter
                    filters={{
                        insight: InsightType.TRENDS,
                        events: (activeStep as AutomationEventSourceStep)?.data?.filters,
                        new_entity: (activeStep as AutomationEventSourceStep)?.data?.new_entity,
                    }}
                    setFilters={(filters: FilterType) => {
                        console.debug('setfilters: ', filters)
                        updateActiveStep(activeStep.id, { filters: filters.events, new_entity: filters.new_entity })
                    }}
                    typeKey={'automation_step_event_sent_config'}
                    buttonCopy={'Action or event filter'}
                    mathAvailability={MathAvailability.None}
                />
            </div>
            {false && (
                <>
                    <div className="mb-2">
                        <LemonLabel showOptional>Event properties</LemonLabel>
                        {/* <p className="text-sm text-muted">{variable.description}</p> */}
                    </div>
                    <div>
                        <PropertyFilters
                            propertyFilters={[]}
                            onChange={() => {}}
                            pageKey={'pageKey'}
                            style={{ marginBottom: 0 }}
                            showNestedArrow
                            eventNames={[]}
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                        />
                    </div>
                    <div className="mb-2">
                        <LemonLabel showOptional>Person and cohort</LemonLabel>
                        {/* <p className="text-sm text-muted">{variable.description}</p> */}
                    </div>
                    <div>
                        <PropertyFilters
                            propertyFilters={[]}
                            onChange={() => {}}
                            pageKey={'pageKey'}
                            style={{ marginBottom: 0 }}
                            showNestedArrow
                            eventNames={[]}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.Cohorts,
                            ]}
                        />
                    </div>
                </>
            )}
        </div>
    )
}

export function AutomationStepConfig({ isOpen }): JSX.Element {
    const { activeStep, activeStepConfig } = useValues(automationStepConfigLogic)
    const { setActiveStepId } = useActions(automationStepConfigLogic)

    if (!isOpen) {
        return null
    }

    return (
        <AutomationStepSidebar onClose={() => setActiveStepId(null)}>
            {activeStep ? (
                <>
                    <h2>New step: {activeStepConfig?.label}</h2>
                    <LemonDivider className="mb-4" />
                    {activeStepConfig?.configComponent}
                </>
            ) : (
                <h2>Error loading step</h2>
            )}
        </AutomationStepSidebar>
    )
}
