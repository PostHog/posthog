import { ActivityChange, ChangeMapping } from 'lib/components/ActivityLog/humanizeActivity'

import { ClearSourceDescriber } from './ClearSourceDescriber'
import { ColumnMappedDescriber } from './ColumnMappedDescriber'
import { ColumnMappingChangedDescriber } from './ColumnMappingChangedDescriber'
import { ColumnUnmappedDescriber } from './ColumnUnmappedDescriber'
import { ConfigurationAddedDescriber } from './ConfigurationAddedDescriber'
import { ConfigurationRemovedDescriber } from './ConfigurationRemovedDescriber'
import { SourceAddedDescriber } from './SourceAddedDescriber'

export const MarketingAnalyticsConfigurationDescriber = (change?: ActivityChange): ChangeMapping | null => {
    if (!change) {
        return null
    }

    // It should always be a record, but we'll be defensive
    const before = (change.before ?? {}) as Record<string, any>
    const after = (change.after ?? {}) as Record<string, any>

    if (!Object.keys(before).length && !Object.keys(after).length) {
        return null
    }

    const descriptions: JSX.Element[] = []

    if (!Object.keys(before).length && Object.keys(after).length) {
        const key = Object.keys(after)[0]
        // First source being configured
        descriptions.push(
            <ConfigurationAddedDescriber
                sourceKey={key}
                columnKey={Object.keys(after[key])[0]}
                mappedField={Object.values(after[key])[0] as string}
            />
        )
    } else if (Object.keys(before).length && !Object.keys(after).length) {
        const key = Object.keys(before)[0]
        // Last source being cleared
        descriptions.push(<ConfigurationRemovedDescriber sourceKey={key} columnKey={Object.keys(before[key])[0]} />)
    } else if (Object.keys(before).length && Object.keys(after).length) {
        const beforeKeys = Object.keys(before)
        const afterKeys = Object.keys(after)

        // Added sources
        for (const key of afterKeys) {
            if (!beforeKeys.includes(key)) {
                descriptions.push(
                    <SourceAddedDescriber
                        sourceKey={key}
                        columnKey={Object.keys(after[key])[0]}
                        mappedField={Object.values(after[key])[0] as string}
                    />
                )
            }
        }
        // Removed sources
        for (const key of beforeKeys) {
            if (!afterKeys.includes(key)) {
                descriptions.push(<ClearSourceDescriber sourceKey={key} columnKey={Object.keys(before[key])[0]} />)
            }
        }
        // Updated sources
        for (const key of afterKeys) {
            if (beforeKeys.includes(key)) {
                const beforeCols = before[key] || {}
                const afterCols = after[key] || {}
                const beforeColKeys = Object.keys(beforeCols)
                const afterColKeys = Object.keys(afterCols)

                // Added columns
                for (const col of afterColKeys) {
                    if (!beforeColKeys.includes(col)) {
                        descriptions.push(
                            <ColumnMappedDescriber sourceKey={key} columnKey={col} mappedField={afterCols[col]} />
                        )
                    }
                }
                // Removed columns
                for (const col of beforeColKeys) {
                    if (!afterColKeys.includes(col)) {
                        descriptions.push(<ColumnUnmappedDescriber sourceKey={key} columnKey={col} />)
                    }
                }
                // Changed columns
                for (const col of afterColKeys) {
                    if (
                        beforeColKeys.includes(col) &&
                        JSON.stringify(beforeCols[col]) !== JSON.stringify(afterCols[col])
                    ) {
                        descriptions.push(
                            <ColumnMappingChangedDescriber
                                sourceKey={key}
                                columnKey={col}
                                oldMapping={beforeCols[col]}
                                newMapping={afterCols[col]}
                            />
                        )
                    }
                }
            }
        }
    }

    if (descriptions.length === 0) {
        return null
    }

    return { description: descriptions }
}
