import { BIConfig, BIField, BIHierarchy, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'

import { BIDrillSelection, getBIDrillQueries } from './biDrilldown'
import { buildBIQuery, mergeBIChartSettings } from './biEditorTypes'
import { normalizeBIConditionGroup } from './biFilterGroups'
import { mergeBITableSettings } from './biMeasureSettings'

export function hierarchyFieldKey(field: BIField): string {
    return JSON.stringify([
        field.source.connectionId ?? null,
        field.source.table,
        field.expression.trim(),
        field.dateBucket ?? null,
        field.datePart ?? null,
    ])
}

export function hierarchyError(hierarchy: BIHierarchy, config: BIConfig): string | undefined {
    if (!hierarchy.name.trim()) {
        return 'Enter a hierarchy name'
    }
    if (
        config.hierarchies?.some(
            (item) => item.id !== hierarchy.id && item.name.toLowerCase() === hierarchy.name.trim().toLowerCase()
        )
    ) {
        return 'Choose a different hierarchy name'
    }
    if (hierarchy.levels.length < 2 || hierarchy.levels.length > 10) {
        return 'Choose between 2 and 10 levels'
    }
    if (
        hierarchy.levels.some(
            (field) =>
                !field.expression.trim() ||
                field.source.table !== config.source?.table ||
                (field.source.connectionId ?? null) !== (config.source?.connectionId ?? null) ||
                (field.localDefinition?.kind === 'expression' && field.localDefinition.aggregate)
        )
    ) {
        return 'Choose dimensions from this worksheet’s data source'
    }
    if (new Set(hierarchy.levels.map(hierarchyFieldKey)).size !== hierarchy.levels.length) {
        return 'Use each level only once'
    }
}

export interface BIHierarchyDrill {
    hierarchy: BIHierarchy
    next: BIField
    worksheet: BIVisualizationNode
}

export function getBIHierarchyDrills(node: BIVisualizationNode, selection: BIDrillSelection): BIHierarchyDrill[] {
    if (!node.config.hierarchies?.length) {
        return []
    }
    const filtered = getBIDrillQueries(node, selection)?.worksheet
    if (!filtered) {
        return []
    }
    const selected = new Set(selection.filters.map((filter) => hierarchyFieldKey(filter.field)))
    const dimensions = [...node.config.rows, ...node.config.columns]
    const previousDefaults = buildBIQuery(node.config)?.node
    return (node.config.hierarchies ?? []).flatMap((hierarchy): BIHierarchyDrill[] => {
        if (hierarchyError(hierarchy, node.config)) {
            return []
        }
        const index = hierarchy.levels.findLastIndex((field) => selected.has(hierarchyFieldKey(field)))
        const current = hierarchy.levels[index]
        const next = hierarchy.levels[index + 1]
        const active = current && dimensions.find((field) => hierarchyFieldKey(field) === hierarchyFieldKey(current))
        if (!active || !next || dimensions.some((field) => hierarchyFieldKey(field) === hierarchyFieldKey(next))) {
            return []
        }
        const replace = (field: BIField): BIField => (field.id === active.id ? { ...next, id: active.id } : field)
        const config: BIConfig = {
            ...filtered.config,
            rows: filtered.config.rows.map(replace),
            columns: filtered.config.columns.map(replace),
            hierarchyDrillPath: [
                ...(node.config.hierarchyDrillPath ?? []),
                {
                    hierarchyId: hierarchy.id,
                    previousField: active,
                    nextField: { ...next, id: active.id },
                    filterIds: filtered.config.filters
                        .filter(
                            (filter) => !node.config.filters.some((original) => original.field.id === filter.field.id)
                        )
                        .map((filter) => filter.field.id),
                },
            ],
        }
        const built = buildBIQuery(config)?.node
        if (!built) {
            return []
        }
        return [
            {
                hierarchy,
                next,
                worksheet: {
                    ...built,
                    kind: NodeKind.BIVisualizationNode,
                    config,
                    chartSettings: mergeBIChartSettings(
                        node.chartSettings,
                        built.chartSettings,
                        previousDefaults?.chartSettings
                    ),
                    tableSettings: mergeBITableSettings(
                        node.tableSettings,
                        built.tableSettings,
                        previousDefaults?.tableSettings
                    ),
                    source: { ...built.source, filters: filtered.source.filters, variables: filtered.source.variables },
                },
            },
        ]
    })
}

export function getBIHierarchyParent(node: BIVisualizationNode): BIVisualizationNode | null {
    const path = node.config.hierarchyDrillPath ?? []
    const step = path.at(-1)
    if (
        !step ||
        !node.config.hierarchies?.some(
            (hierarchy) => hierarchy.id === step.hierarchyId && !hierarchyError(hierarchy, node.config)
        )
    ) {
        return null
    }
    const hierarchy = node.config.hierarchies.find((hierarchy) => hierarchy.id === step.hierarchyId)!
    const previousIndex = hierarchy.levels.findIndex(
        (field) => hierarchyFieldKey(field) === hierarchyFieldKey(step.previousField)
    )
    if (
        previousIndex < 0 ||
        !hierarchy.levels[previousIndex + 1] ||
        hierarchyFieldKey(hierarchy.levels[previousIndex + 1]) !== hierarchyFieldKey(step.nextField)
    ) {
        return null
    }
    const active = [...node.config.rows, ...node.config.columns].find(
        (field) => field.id === step.nextField.id && hierarchyFieldKey(field) === hierarchyFieldKey(step.nextField)
    )
    if (!active) {
        return null
    }
    const filters = node.config.filters.filter((filter) => !step.filterIds.includes(filter.field.id))
    const replace = (field: BIField): BIField => (field.id === active.id ? step.previousField : field)
    const config: BIConfig = {
        ...node.config,
        rows: node.config.rows.map(replace),
        columns: node.config.columns.map(replace),
        filters,
        rowFilterGroup: normalizeBIConditionGroup(
            node.config.rowFilterGroup,
            filters.map((filter) => filter.field.id)
        ),
        hierarchyDrillPath: path.slice(0, -1),
    }
    const built = buildBIQuery(config)?.node
    const previousDefaults = buildBIQuery(node.config)?.node
    return built
        ? {
              ...built,
              kind: NodeKind.BIVisualizationNode,
              config,
              chartSettings: mergeBIChartSettings(
                  node.chartSettings,
                  built.chartSettings,
                  previousDefaults?.chartSettings
              ),
              tableSettings: mergeBITableSettings(
                  node.tableSettings,
                  built.tableSettings,
                  previousDefaults?.tableSettings
              ),
              source: { ...built.source, filters: node.source.filters, variables: node.source.variables },
          }
        : null
}
