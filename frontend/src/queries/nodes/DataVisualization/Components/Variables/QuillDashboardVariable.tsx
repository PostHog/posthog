import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Button,
    Field,
    FieldLabel,
    Popover,
    PopoverContent,
    PopoverTrigger,
    SelectTriggerIcon,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { Variable } from '../../types'
import { QuillListVariableSelect } from './QuillListVariableSelect'
import { QuillVariableInput } from './QuillVariableInput'
import { getVariableDisplayValue } from './variableUtils'

interface QuillDashboardVariableProps {
    variable: Variable
    insightsUsingVariable: string[]
    onChange: (variableId: string, value: any, isNull: boolean) => void
}

export function QuillDashboardVariable({
    variable,
    insightsUsingVariable,
    onChange,
}: QuillDashboardVariableProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const displayValue = variable.isNull ? 'Set to null' : getVariableDisplayValue(variable)

    return (
        <Field className="w-auto gap-1">
            <FieldLabel className="items-center gap-1">
                {variable.name}
                {insightsUsingVariable.length > 0 && (
                    <Tooltip>
                        <TooltipTrigger render={<span className="inline-flex text-muted-foreground" />}>
                            <IconInfo />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-64">
                            Insights using this variable: {insightsUsingVariable.join(', ')}
                        </TooltipContent>
                    </Tooltip>
                )}
            </FieldLabel>
            {variable.type === 'List' ? (
                <QuillListVariableSelect variable={variable} onChange={onChange} />
            ) : (
                <Popover open={open} onOpenChange={setOpen}>
                    <PopoverTrigger render={<Button variant="outline" className="min-w-32 max-w-80 justify-between" />}>
                        {displayValue ? (
                            <span className="min-w-0 truncate">{displayValue}</span>
                        ) : (
                            <span className="min-w-0 truncate italic text-muted-foreground">No override set</span>
                        )}
                        <SelectTriggerIcon />
                    </PopoverTrigger>
                    <PopoverContent align="start" className="w-auto p-2">
                        <QuillVariableInput
                            variable={variable}
                            onChange={onChange}
                            closePopover={() => setOpen(false)}
                        />
                    </PopoverContent>
                </Popover>
            )}
        </Field>
    )
}
