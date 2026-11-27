import { useId } from 'react'

import {
    Button,
    Card,
    CardGroup,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Field,
    FieldLabel,
    FieldTitle,
    Input,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import {
    conversionGoalDescription,
    conversionGoalNamePlaceholder,
    getConfiguredConversionGoalsLabel,
} from '../settings/constants'

export function QuillConversionGoalModal({
    isOpen,
    onClose,
    goalName,
    onGoalNameChange,
    conversionGoalDropdown,
    savedGoals,
    onLoadGoal,
    hasAppliedGoal,
    hasChanges,
    onClear,
    onSave,
    onApply,
}: {
    isOpen: boolean
    onClose: () => void
    goalName: string
    onGoalNameChange: (name: string) => void
    conversionGoalDropdown: JSX.Element
    savedGoals: ConversionGoalFilter[]
    onLoadGoal: (goal: ConversionGoalFilter) => void
    hasAppliedGoal: boolean
    hasChanges: boolean
    onClear: () => void
    onSave: () => void
    onApply: () => void
}): JSX.Element {
    const nameId = useId()

    return (
        <Credenza open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <CredenzaContent className="md:max-w-150">
                <CredenzaHeader>
                    <CredenzaTitle>Conversion goal</CredenzaTitle>
                </CredenzaHeader>
                <CredenzaBody>
                    <div className="flex flex-col gap-4">
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {conversionGoalDescription}
                            <Button
                                variant="link"
                                size="inline"
                                render={<LinkPrimitive to={urls.settings('environment-marketing-analytics')} />}
                            >
                                Manage saved conversion goals in settings
                            </Button>
                            .
                        </Text>

                        <Field>
                            <FieldLabel htmlFor={nameId}>Conversion goal name</FieldLabel>
                            <Input
                                id={nameId}
                                value={goalName}
                                onChange={(event) => onGoalNameChange(event.target.value)}
                                placeholder={conversionGoalNamePlaceholder}
                            />
                        </Field>

                        <Field>
                            <FieldTitle>Event or table</FieldTitle>
                            <div data-not-quill>{conversionGoalDropdown}</div>
                        </Field>

                        {savedGoals.length > 0 && (
                            <Collapsible>
                                <CollapsibleTrigger>
                                    {getConfiguredConversionGoalsLabel(savedGoals.length)}
                                </CollapsibleTrigger>
                                <CollapsibleContent>
                                    <CardGroup size="sm">
                                        {savedGoals.map((goal) => (
                                            <Card key={goal.conversion_goal_id} size="sm" className="p-0">
                                                <button
                                                    type="button"
                                                    className="flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                                    onClick={() => onLoadGoal(goal)}
                                                >
                                                    <Text
                                                        size="xs"
                                                        weight="medium"
                                                        render={<span className="m-0 truncate" />}
                                                    >
                                                        {goal.conversion_goal_name}
                                                    </Text>
                                                    <Text
                                                        size="xs"
                                                        variant="muted"
                                                        render={<span className="m-0 truncate" />}
                                                    >
                                                        {goal.custom_name || goal.name}
                                                    </Text>
                                                </button>
                                            </Card>
                                        ))}
                                    </CardGroup>
                                </CollapsibleContent>
                            </Collapsible>
                        )}
                    </div>
                </CredenzaBody>
                <CredenzaFooter className="sm:justify-between">
                    <Button
                        variant="outline"
                        onClick={onClear}
                        disabledReason={!hasAppliedGoal ? 'No active goal to clear' : undefined}
                    >
                        Clear
                    </Button>
                    <div className="flex flex-col-reverse gap-2 sm:flex-row">
                        <Button
                            variant="outline"
                            onClick={onSave}
                            disabledReason={
                                !hasAppliedGoal
                                    ? 'Apply first to verify your conversion goal works correctly'
                                    : undefined
                            }
                        >
                            Save
                        </Button>
                        <Button
                            variant="primary"
                            onClick={onApply}
                            disabledReason={!hasChanges ? 'No changes to apply' : undefined}
                        >
                            Apply
                        </Button>
                    </div>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
