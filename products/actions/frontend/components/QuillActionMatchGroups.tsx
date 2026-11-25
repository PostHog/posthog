import { Field as KeaField } from 'kea-forms'

import { IconPlus } from '@posthog/icons'
import { Button, Skeleton } from '@posthog/quill'

import { ActionStepType, ActionType } from '~/types'

import { DEFAULT_ACTION_STEP } from '../logics/actionEditLogic'
import { withActionStepAt, withoutActionStep } from '../utils/actionStepEdits'
import { QuillActionSection } from './QuillActionSection'
import { QuillActionStep } from './QuillActionStep'

/** The action's match groups, bound to the `steps` field of the action form. */
export function QuillActionMatchGroups({
    action,
    actionLoading,
    disabledReason,
}: {
    action: ActionType
    actionLoading?: boolean
    disabledReason?: string
}): JSX.Element {
    return (
        <QuillActionSection
            title="Match groups"
            description={
                <>
                    Your action will be triggered whenever <b>any of your match groups</b> are received.
                </>
            }
        >
            {actionLoading ? (
                <div className="flex gap-2">
                    <Skeleton className="h-64 w-1/2" />
                    <Skeleton className="h-64 w-1/2" />
                </div>
            ) : (
                <KeaField name="steps" noStyle>
                    {({
                        value: steps,
                        onChange,
                    }: {
                        value: ActionStepType[]
                        onChange: (steps: ActionStepType[]) => void
                    }) => (
                        <div className="@container">
                            <div className="grid gap-3 @4xl:grid-cols-2">
                                {steps.map((step, index) => (
                                    <QuillActionStep
                                        // A key from the step's content would remount its property filters, and their
                                        // logics, on every keystroke. The filters pick up content changes themselves.
                                        key={index}
                                        identifier={`action-${action.id || 'new'}-step-${index}`}
                                        index={index}
                                        step={step}
                                        actionId={action.id || 0}
                                        isOnlyStep={steps.length === 1}
                                        disabledReason={disabledReason}
                                        onDelete={() => onChange(withoutActionStep(steps, index))}
                                        onChange={(newStep) => onChange(withActionStepAt(steps, index, newStep))}
                                    />
                                ))}
                                <Button
                                    variant="outline"
                                    className="h-full w-full"
                                    onClick={() => onChange([...(action.steps || []), DEFAULT_ACTION_STEP])}
                                    disabledReason={disabledReason}
                                >
                                    <IconPlus />
                                    Add match group
                                </Button>
                            </div>
                        </div>
                    )}
                </KeaField>
            )}
        </QuillActionSection>
    )
}
