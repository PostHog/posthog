import { useValues } from 'kea'
import { useId } from 'react'

import { Field, FieldLabel, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { ListVariable } from '~/queries/nodes/DataVisualization/types'

import {
    POSTHOG_WAREHOUSE,
    connectionSelectorLogic,
    getConnectionOptionLabel,
} from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'

export interface QuillVariableConnectionSelectProps {
    variable: ListVariable
    updateVariable: (variable: ListVariable) => void
}

/** Picks the connection a list variable's options query runs on. Hidden while PostHog is the only connection. */
export function QuillVariableConnectionSelect({
    variable,
    updateVariable,
}: QuillVariableConnectionSelectProps): JSX.Element | null {
    const id = useId()
    const { connectionOptions } = useValues(connectionSelectorLogic())

    if ((connectionOptions?.length ?? 0) === 0 && !variable.values_query_connection_id) {
        return null
    }

    const items = [
        { value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' },
        ...(connectionOptions ?? []).map((source) => ({
            value: source.id,
            label: getConnectionOptionLabel(source),
        })),
    ]

    return (
        <Field>
            <FieldLabel htmlFor={id}>Connection</FieldLabel>
            <Select<string>
                items={items}
                value={variable.values_query_connection_id ?? POSTHOG_WAREHOUSE}
                onValueChange={(value) =>
                    updateVariable({
                        ...variable,
                        values_query_connection_id: !value || value === POSTHOG_WAREHOUSE ? null : value,
                    })
                }
            >
                <SelectTrigger id={id} className="w-full">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {items.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                            {item.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </Field>
    )
}
