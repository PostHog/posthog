import { BIValue } from '~/queries/schema/schema-business-intelligence'
import { ChartAxis, TableSettings } from '~/queries/schema/schema-general'

export function isBIMeasureSettings(value: Partial<BIValue>): boolean {
    const format = value.formatting
    const display = value.display
    return (
        (format === undefined ||
            (!!format &&
                typeof format === 'object' &&
                [format.prefix, format.suffix].every((text) => text === undefined || typeof text === 'string') &&
                (format.style === undefined || ['none', 'number', 'short', 'percent'].includes(format.style)) &&
                (format.decimalPlaces === undefined ||
                    (Number.isInteger(format.decimalPlaces) &&
                        format.decimalPlaces >= 0 &&
                        format.decimalPlaces <= 12)))) &&
        (display === undefined ||
            (!!display &&
                typeof display === 'object' &&
                [display.label, display.color].every((text) => text === undefined || typeof text === 'string') &&
                (display.trendLine === undefined || typeof display.trendLine === 'boolean') &&
                (display.yAxisPosition === undefined || ['left', 'right'].includes(display.yAxisPosition)) &&
                (display.displayType === undefined || ['auto', 'line', 'bar', 'area'].includes(display.displayType))))
    )
}

export function getBIMeasureSettings(value: BIValue): ChartAxis['settings'] {
    const formatting =
        value.formatting ??
        (['percent_of_total', 'percent_change'].includes(value.tableCalculation?.type ?? '')
            ? { style: 'percent' as const, decimalPlaces: 1 }
            : undefined)
    return formatting || value.display
        ? {
              ...(formatting ? { formatting } : {}),
              ...(value.display ? { display: value.display } : {}),
          }
        : undefined
}

export function mergeBITableSettings(
    current: TableSettings | undefined,
    generated: TableSettings | undefined
): TableSettings | undefined {
    if (!generated) {
        return current
    }
    return {
        ...current,
        ...generated,
        columns: generated.columns?.map((column) => {
            const saved = current?.columns?.find((previous) => previous.column === column.column)
            return { ...saved, ...column, settings: { ...saved?.settings, ...column.settings } }
        }),
    }
}
