import { z } from 'zod'

import type { TileAction } from '../../tiles/tileAction'
import type { WidgetMenuContext } from '../widgetDefinition'
import type { ChartConfig } from './chartSpec'
import type { VizSpec } from './vizTypes'

type Options = Record<string, unknown>

function optionLabel(key: string, field: z.ZodType): string {
    return field.description ?? key.charAt(0).toUpperCase() + key.slice(1)
}

/** A menu entry for each option a kind of chart declares: a checkbox for a boolean, a submenu of choices for an enum. */
function optionActions(
    viz: VizSpec,
    { widget, setConfig, disabledReason }: WidgetMenuContext<ChartConfig>
): TileAction[] {
    if (!(viz.optionsSchema instanceof z.ZodObject)) {
        return []
    }
    const options = (widget.config.viz.options ?? {}) as Options
    const setOption = (key: string, value: unknown): void =>
        setConfig({ ...widget.config, viz: { ...widget.config.viz, options: { ...options, [key]: value } } })

    return Object.entries(viz.optionsSchema.shape as Record<string, z.ZodType>).flatMap(
        ([key, field]): TileAction[] => {
            const inner = field instanceof z.ZodOptional ? (field.unwrap() as z.ZodType) : field
            const label = optionLabel(key, field)
            const dataAttr = `dashboard-v2-chart-option-${key}`
            if (inner instanceof z.ZodBoolean) {
                const checked = options[key] === true
                return [{ key, label, dataAttr, disabledReason, checked, onSelect: () => setOption(key, !checked) }]
            }
            if (inner instanceof z.ZodEnum) {
                return [
                    {
                        key,
                        label,
                        dataAttr,
                        disabledReason,
                        choice: true,
                        submenu: (inner.options as string[]).map((value) => ({
                            key: value,
                            label: value.charAt(0).toUpperCase() + value.slice(1),
                            dataAttr: `${dataAttr}-${value}`,
                            disabledReason,
                            checked: options[key] === value,
                            onSelect: () => setOption(key, value),
                        })),
                    },
                ]
            }
            return []
        }
    )
}

/**
 * The chart's own menu entries: a "Chart type" submenu that switches the kind of chart, and the options the current
 * kind declares in its schema. Switching kind keeps the query and drops options the new kind does not have.
 */
export function chartMenuActions(vizTypes: VizSpec[], context: WidgetMenuContext<ChartConfig>): TileAction[] {
    const { widget, setConfig, disabledReason } = context
    const current = vizTypes.find((viz) => viz.type === widget.config.viz.type)
    const actions: TileAction[] = [
        {
            key: 'chart-type',
            group: 'display',
            choice: true,
            label: 'Chart type',
            dataAttr: 'dashboard-v2-chart-type',
            disabledReason,
            submenu: vizTypes.map((viz) => ({
                key: viz.type,
                label: viz.label,
                dataAttr: `dashboard-v2-chart-type-${viz.type}`,
                disabledReason,
                checked: viz.type === widget.config.viz.type,
                onSelect: () => setConfig({ ...widget.config, viz: { type: viz.type } }),
            })),
        },
    ]
    const options = current ? optionActions(current, context) : []
    if (options.length > 0) {
        actions.push({
            key: 'chart-options',
            group: 'display',
            label: 'Chart options',
            dataAttr: 'dashboard-v2-chart-options',
            disabledReason,
            submenu: options,
        })
    }
    return actions
}
