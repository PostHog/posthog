import { useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Card, CardContent, CardHeader, CardTitle, Field, FieldLabel } from '@posthog/quill'

import { OperandTag } from 'lib/components/PropertyFilters/components/OperandTag'
import { DEFAULT_TAXONOMIC_GROUP_TYPES } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { groupsModel } from '~/models/groupsModel'
import { ActionStepType, AnyPropertyFilter } from '~/types'

import { actionStepFilters, actionStepTypeOption, withActionStepFilters } from '../utils/actionStepEdits'
import { EventHealthWarning } from './EventHealthWarning'
import { QuillActionStepAutocapture } from './QuillActionStepAutocapture'
import { QuillActionStepEventName } from './QuillActionStepEventName'
import { QuillActionStepMatchedField } from './QuillActionStepMatchedField'
import { QuillActionStepScreenName } from './QuillActionStepScreenName'
import { QuillActionStepTypeSwitcher } from './QuillActionStepTypeSwitcher'

/** One match group of an action. Render it inside a quill surface, so its shared pickers and filters render in quill. */
export function QuillActionStep({
    step,
    actionId,
    isOnlyStep,
    index,
    identifier,
    disabledReason,
    onDelete,
    onChange: sendStep,
}: {
    step: ActionStepType
    actionId: number
    isOnlyStep: boolean
    index: number
    identifier: string
    disabledReason?: string
    onDelete: () => void
    onChange: (step: ActionStepType) => void
}): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const typeOption = actionStepTypeOption(step)

    return (
        // The card clips its overflow, so the "or" tag sits on a wrapper to reach into the gap beside the card.
        <div className="relative">
            {index % 2 === 1 && (
                <div className="absolute top-1/2 -left-5 z-10">
                    <OperandTag operand="or" />
                </div>
            )}
            <Card size="sm" className="h-full">
                <CardHeader className="flex flex-row items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <CardTitle>Match group #{index + 1}</CardTitle>
                        <EventHealthWarning event={step.event} />
                    </div>
                    {!isOnlyStep && (
                        <Button
                            variant="default"
                            size="icon-sm"
                            aria-label="delete"
                            onClick={onDelete}
                            disabledReason={disabledReason}
                        >
                            <IconX />
                        </Button>
                    )}
                </CardHeader>
                <CardContent className="flex flex-col gap-4">
                    <QuillActionStepTypeSwitcher step={step} sendStep={sendStep} disabledReason={disabledReason} />

                    {typeOption === '$autocapture' && (
                        <QuillActionStepAutocapture
                            step={step}
                            sendStep={sendStep}
                            actionId={actionId}
                            disabledReason={disabledReason}
                        />
                    )}
                    {typeOption === 'event' && (
                        <QuillActionStepEventName step={step} sendStep={sendStep} disabledReason={disabledReason} />
                    )}
                    {typeOption === '$pageview' && (
                        <QuillActionStepMatchedField
                            step={step}
                            sendStep={sendStep}
                            field="url"
                            label="URL"
                            disabledReason={disabledReason}
                        />
                    )}
                    {typeOption === '$screen' && (
                        <QuillActionStepScreenName step={step} sendStep={sendStep} disabledReason={disabledReason} />
                    )}

                    <Field>
                        <FieldLabel>Filters</FieldLabel>
                        <PropertyFilters
                            propertyFilters={actionStepFilters(step)}
                            pageKey={identifier}
                            eventNames={step.event ? [step.event] : []}
                            taxonomicGroupTypes={[...DEFAULT_TAXONOMIC_GROUP_TYPES, ...groupsTaxonomicTypes]}
                            onChange={(properties) =>
                                sendStep(withActionStepFilters(step, properties as AnyPropertyFilter[]))
                            }
                            showConditionBadge
                            disabledReason={disabledReason}
                        />
                    </Field>
                </CardContent>
            </Card>
        </div>
    )
}
