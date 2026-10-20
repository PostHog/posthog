import { IconGear, IconTrash } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Input,
} from '@posthog/quill'

import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'
import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'

import { GoalLine } from '~/queries/schema/schema-general'

import type { GoalLinesListProps } from './GoalLinesList'

export interface QuillGoalLinesListProps extends GoalLinesListProps {
    /** The colour control for one line; quill has no colour picker, so the caller supplies it. */
    renderColorPicker: (goalLineIndex: number, borderColor: string | undefined) => React.ReactNode
}

export function QuillGoalLinesList({
    goalLines,
    updateGoalLine,
    removeGoalLine,
    allowCalculations = false,
    calculationDisabledReason,
    renderColorPicker,
}: QuillGoalLinesListProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {goalLines.map(
                (
                    { label, value = 0, displayLabel = true, position, borderColor, calculation, scope },
                    goalLineIndex
                ) => (
                    <div key={goalLineIndex} className="flex flex-col gap-1">
                        {allowCalculations && (
                            <div className="flex flex-wrap gap-1">
                                <QuillSelect<NonNullable<GoalLine['calculation']>>
                                    aria-label={`Reference line ${goalLineIndex + 1} calculation`}
                                    value={calculation ?? 'fixed'}
                                    onChange={(newValue) => updateGoalLine(goalLineIndex, 'calculation', newValue)}
                                    options={[
                                        { value: 'fixed', label: 'Constant' },
                                        { value: 'mean', label: 'Mean', disabledReason: calculationDisabledReason },
                                        { value: 'median', label: 'Median', disabledReason: calculationDisabledReason },
                                        { value: 'min', label: 'Minimum', disabledReason: calculationDisabledReason },
                                        { value: 'max', label: 'Maximum', disabledReason: calculationDisabledReason },
                                    ]}
                                />
                                {calculation && calculation !== 'fixed' && (
                                    <QuillSelect<NonNullable<GoalLine['scope']>>
                                        aria-label={`Reference line ${goalLineIndex + 1} scope`}
                                        value={scope ?? 'all'}
                                        onChange={(newValue) => updateGoalLine(goalLineIndex, 'scope', newValue)}
                                        options={[
                                            { value: 'all', label: 'Across all series' },
                                            { value: 'series', label: 'Per series' },
                                        ]}
                                    />
                                )}
                            </div>
                        )}
                        <div className="flex flex-1 flex-wrap gap-1 items-center">
                            {renderColorPicker(goalLineIndex, borderColor)}
                            <Input
                                placeholder="Label"
                                aria-label={`Goal line ${goalLineIndex + 1} label`}
                                className="min-w-0 flex-1"
                                value={label}
                                onChange={(event) => updateGoalLine(goalLineIndex, 'label', event.target.value)}
                            />
                            {(!allowCalculations || !calculation || calculation === 'fixed') && (
                                <Input
                                    type="number"
                                    step="any"
                                    placeholder="Value"
                                    aria-label={`Goal line ${goalLineIndex + 1} value`}
                                    className="w-24"
                                    value={value}
                                    onChange={(event) => {
                                        const parsed = event.target.valueAsNumber
                                        updateGoalLine(goalLineIndex, 'value', Number.isNaN(parsed) ? 0 : parsed)
                                    }}
                                />
                            )}
                            <DropdownMenu>
                                <DropdownMenuTrigger
                                    render={<QuillIconButton label="Goal line settings" icon={<IconGear />} />}
                                />
                                <DropdownMenuContent align="end" className="min-w-44">
                                    <DropdownMenuGroup>
                                        <DropdownMenuLabel>Label settings</DropdownMenuLabel>
                                        <DropdownMenuCheckboxItem
                                            checked={displayLabel}
                                            onCheckedChange={(checked: boolean) =>
                                                updateGoalLine(goalLineIndex, 'displayLabel', checked)
                                            }
                                            closeOnClick={false}
                                            data-attr="goal-line-show-label-switch"
                                        >
                                            Show label
                                        </DropdownMenuCheckboxItem>
                                    </DropdownMenuGroup>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuGroup>
                                        <DropdownMenuLabel>Label position</DropdownMenuLabel>
                                        <DropdownMenuRadioGroup
                                            value={position ?? 'end'}
                                            onValueChange={(newValue) =>
                                                updateGoalLine(goalLineIndex, 'position', newValue as 'start' | 'end')
                                            }
                                            data-attr="goal-line-position-selector"
                                        >
                                            <DropdownMenuRadioItem
                                                value="start"
                                                disabled={!displayLabel}
                                                closeOnClick={false}
                                            >
                                                Start
                                            </DropdownMenuRadioItem>
                                            <DropdownMenuRadioItem
                                                value="end"
                                                disabled={!displayLabel}
                                                closeOnClick={false}
                                            >
                                                End
                                            </DropdownMenuRadioItem>
                                        </DropdownMenuRadioGroup>
                                    </DropdownMenuGroup>
                                </DropdownMenuContent>
                            </DropdownMenu>
                            <QuillIconButton
                                label="Delete goal line"
                                icon={<IconTrash />}
                                onClick={() => removeGoalLine(goalLineIndex)}
                            />
                        </div>
                    </div>
                )
            )}
        </div>
    )
}
