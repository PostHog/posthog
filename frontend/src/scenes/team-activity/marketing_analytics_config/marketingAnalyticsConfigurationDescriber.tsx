import { ActivityChange, ChangeMapping } from 'lib/components/ActivityLog/humanizeActivity'
import { objectsEqual } from 'lib/utils'

import { MarketingAnalyticsConfig, SourceMap } from '~/queries/schema/schema-general'

import { ClearSourceDescriber } from './ClearSourceDescriber'
import { ColumnMappedDescriber } from './ColumnMappedDescriber'
import { ColumnMappingChangedDescriber } from './ColumnMappingChangedDescriber'
import { ColumnUnmappedDescriber } from './ColumnUnmappedDescriber'
import { ConfigurationAddedDescriber } from './ConfigurationAddedDescriber'
import { ConfigurationRemovedDescriber } from './ConfigurationRemovedDescriber'
import { SourceAddedDescriber } from './SourceAddedDescriber'

export const marketingAnalyticsConfigurationDescriber = (change?: ActivityChange): ChangeMapping | null => {
    if (!change) {
        return null
    }

    const sourceMapDescriptions = marketingAnalyticsSourceMapDescriber(change) ?? []

    return { description: [...sourceMapDescriptions] }
}

const marketingAnalyticsSourceMapDescriber = (change?: ActivityChange): JSX.Element[] | null => {
    if (!change) {
        return null
    }

    const sourceMapBefore: Record<string, SourceMap> = (change.before as MarketingAnalyticsConfig)?.sources_map ?? {}
    const sourceMapAfter: Record<string, SourceMap> = (change.after as MarketingAnalyticsConfig)?.sources_map ?? {}

    if (!Object.keys(sourceMapBefore).length && !Object.keys(sourceMapAfter).length) {
        return null
    }

    const sourceMapDescriptions: JSX.Element[] = []

    if (!Object.keys(sourceMapBefore).length && Object.keys(sourceMapAfter).length) {
        const key = Object.keys(sourceMapAfter)[0]
        const value = Object.values(sourceMapAfter[key])[0]
        if (value) {
            // First source being configured
            sourceMapDescriptions.push(
                <ConfigurationAddedDescriber
                    sourceKey={key}
                    columnKey={Object.keys(sourceMapAfter[key])[0]}
                    mappedField={value}
                />
            )
        }
    } else if (Object.keys(sourceMapBefore).length && !Object.keys(sourceMapAfter).length) {
        const key = Object.keys(sourceMapBefore)[0]
        // Last source being cleared
        sourceMapDescriptions.push(
            <ConfigurationRemovedDescriber sourceKey={key} columnKey={Object.keys(sourceMapBefore[key])[0]} />
        )
    } else if (Object.keys(sourceMapBefore).length && Object.keys(sourceMapAfter).length) {
        const beforeKeys = Object.keys(sourceMapBefore)
        const afterKeys = Object.keys(sourceMapAfter)

        // Added sources
        for (const key of afterKeys) {
            if (!beforeKeys.includes(key)) {
                const value = Object.values(sourceMapAfter[key])[0]
                if (value) {
                    sourceMapDescriptions.push(
                        <SourceAddedDescriber
                            sourceKey={key}
                            columnKey={Object.keys(sourceMapAfter[key])[0]}
                            mappedField={value}
                        />
                    )
                }
            }
        }
        // Removed sources
        for (const key of beforeKeys) {
            if (!afterKeys.includes(key)) {
                sourceMapDescriptions.push(
                    <ClearSourceDescriber sourceKey={key} columnKey={Object.keys(sourceMapBefore[key])[0]} />
                )
            }
        }
        // Updated sources
        for (const key of afterKeys) {
            if (beforeKeys.includes(key)) {
                const beforeCols = sourceMapBefore[key] || {}
                const afterCols = sourceMapAfter[key] || {}
                const beforeColKeys = Object.keys(beforeCols)
                const afterColKeys = Object.keys(afterCols)

                // Added columns
                for (const col of afterColKeys) {
                    if (!beforeColKeys.includes(col)) {
                        const mappedField = afterCols[col]
                        if (mappedField) {
                            sourceMapDescriptions.push(
                                <ColumnMappedDescriber sourceKey={key} columnKey={col} mappedField={mappedField} />
                            )
                        }
                    }
                }
                // Removed columns
                for (const col of beforeColKeys) {
                    if (!afterColKeys.includes(col)) {
                        sourceMapDescriptions.push(<ColumnUnmappedDescriber sourceKey={key} columnKey={col} />)
                    }
                }
                // Changed columns
                for (const col of afterColKeys) {
                    if (beforeColKeys.includes(col) && !objectsEqual(beforeCols[col], afterCols[col])) {
                        const oldMapping = beforeCols[col]
                        const newMapping = afterCols[col]
                        if (oldMapping && newMapping) {
                            sourceMapDescriptions.push(
                                <ColumnMappingChangedDescriber
                                    sourceKey={key}
                                    columnKey={col}
                                    oldMapping={oldMapping}
                                    newMapping={newMapping}
                                />
                            )
                        }
                    }
                }
            }
        }
    }

    if (sourceMapDescriptions.length === 0) {
        return null
    }

    return sourceMapDescriptions
}
