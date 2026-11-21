import { useState } from 'react'

import { Button, Input, Label, Separator, Switch, ToggleGroup, ToggleGroupItem, cn } from '@posthog/quill'

import { Variable } from '../../types'
import { QuillVariableDateField } from './QuillVariableDateField'
import { getInitialVariableInputValue, isRelativeDateValue } from './variableUtils'

interface QuillVariableInputProps {
    variable: Exclude<Variable, { type: 'List' }>
    onChange: (variableId: string, value: any, isNull: boolean) => void
    closePopover: () => void
}

export function QuillVariableInput({ variable, onChange, closePopover }: QuillVariableInputProps): JSX.Element {
    const [localInputValue, setLocalInputValue] = useState(() => String(getInitialVariableInputValue(variable)))
    const [isNull, setIsNull] = useState<boolean>(variable.isNull ?? false)
    const calendarOwnsApply = variable.type === 'Date' && !isRelativeDateValue(localInputValue)
    const nullSwitchId = `variable-${variable.id}-null`

    const commit = (value: any): void => {
        onChange(variable.id, value, isNull)
        closePopover()
    }
    const committedValue = (): any => (variable.type === 'Number' ? Number(localInputValue) : localInputValue)

    return (
        <div className="flex min-w-80 flex-col gap-2">
            <div className={cn('flex gap-1', isNull && 'pointer-events-none opacity-50')}>
                {(variable.type === 'String' || variable.type === 'Number') && (
                    <Input
                        autoFocus
                        type={variable.type === 'Number' ? 'number' : 'text'}
                        placeholder="Value..."
                        className="flex-1"
                        value={localInputValue}
                        onChange={(event) => setLocalInputValue(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                commit(committedValue())
                            }
                        }}
                    />
                )}
                {variable.type === 'Boolean' && (
                    <ToggleGroup
                        className="grow"
                        value={[localInputValue]}
                        onValueChange={(next: string[]) => next[0] && setLocalInputValue(next[0])}
                    >
                        <ToggleGroupItem value="true" className="flex-1">
                            true
                        </ToggleGroupItem>
                        <ToggleGroupItem value="false" className="flex-1">
                            false
                        </ToggleGroupItem>
                    </ToggleGroup>
                )}
                {variable.type === 'Date' && (
                    <QuillVariableDateField value={localInputValue} onChange={setLocalInputValue} onApply={commit} />
                )}
                {!calendarOwnsApply && (
                    <Button variant="primary" className="self-start" onClick={() => commit(committedValue())}>
                        Update
                    </Button>
                )}
            </div>
            <Separator />
            <div className="flex items-center gap-2">
                <Switch
                    id={nullSwitchId}
                    size="sm"
                    checked={isNull}
                    onCheckedChange={(checked: boolean) => {
                        setIsNull(checked)
                        onChange(variable.id, null, checked)
                    }}
                />
                <Label htmlFor={nullSwitchId}>Set to null</Label>
            </div>
        </div>
    )
}
