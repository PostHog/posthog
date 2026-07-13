// Guards FE Zod config shape against backend/OpenAPI pydantic drift (cheap SSOT check).
import configPropertyMetadata from '../generated/widget-config-property-keys.json'
import {
    activityEventsWidgetConfigSchema,
    errorTrackingWidgetConfigSchema,
    experimentResultsWidgetConfigSchema,
    experimentsWidgetConfigSchema,
    logsWidgetConfigSchema,
    sessionReplayWidgetConfigSchema,
    surveyResultsWidgetConfigSchema,
    widgetFilterEntrySchema,
} from '../generated/widget-configs.zod'

const WIDGET_CONFIG_SCHEMAS = {
    activity_events_list: activityEventsWidgetConfigSchema,
    error_tracking_list: errorTrackingWidgetConfigSchema,
    session_replay_list: sessionReplayWidgetConfigSchema,
    experiments_list: experimentsWidgetConfigSchema,
    experiment_results: experimentResultsWidgetConfigSchema,
    logs_list: logsWidgetConfigSchema,
    survey_results: surveyResultsWidgetConfigSchema,
} as const

type SchemaNode = { _zod?: { def?: ZodDef } }

type ZodDef = {
    type?: string
    innerType?: SchemaNode
    options?: readonly SchemaNode[]
    valueType?: SchemaNode
    element?: SchemaNode
    shape?: Record<string, SchemaNode>
    entries?: Record<string, unknown>
}

function zodDef(schema: SchemaNode): ZodDef | undefined {
    return schema._zod?.def
}

function unwrapZod(schema: SchemaNode): SchemaNode {
    let current = schema
    // eslint-disable-next-line no-constant-condition
    while (true) {
        const def = zodDef(current)
        if (def?.type === 'optional' || def?.type === 'nullable' || def?.type === 'default') {
            current = def.innerType ?? current
            continue
        }
        break
    }
    return current
}

function zodPropertyTree(schema: SchemaNode): unknown {
    const unwrapped = unwrapZod(schema)
    const def = zodDef(unwrapped)

    if (def?.type === 'object' && def.shape) {
        return Object.fromEntries(Object.entries(def.shape).map(([key, value]) => [key, zodPropertyTree(value)]))
    }

    if (def?.type === 'record' && def.valueType) {
        return {
            $record: zodPropertyTree(def.valueType),
        }
    }

    if (def?.type === 'array' && def.element) {
        return {
            $array: zodPropertyTree(def.element),
        }
    }

    if (def?.type === 'enum' && def.entries) {
        return { $enum: Object.keys(def.entries).sort() }
    }

    if (def?.type === 'union' && def.options) {
        const substantiveOptions = def.options.filter((option) => zodDef(unwrapZod(option))?.type !== 'null')
        if (substantiveOptions.length === 1) {
            return zodPropertyTree(substantiveOptions[0]!)
        }
        const objectArm = substantiveOptions.find((option) => zodDef(unwrapZod(option))?.type === 'object')
        if (objectArm) {
            return zodPropertyTree(objectArm)
        }
        const enumArm = substantiveOptions.find((option) => zodDef(unwrapZod(option))?.type === 'enum')
        if (enumArm) {
            return zodPropertyTree(enumArm)
        }
        const hasStringArm = substantiveOptions.some((option) => zodDef(unwrapZod(option))?.type === 'string')
        const hasArrayArm = substantiveOptions.some((option) => zodDef(unwrapZod(option))?.type === 'array')
        if (hasStringArm && hasArrayArm) {
            return { $types: ['string'] }
        }

        const primitiveTypes = substantiveOptions
            .map((option) => unwrapZod(option))
            .flatMap((option) => {
                const optionDef = zodDef(option)
                if (optionDef?.type === 'string') {
                    return ['string']
                }
                if (optionDef?.type === 'number') {
                    return ['integer']
                }
                if (optionDef?.type === 'boolean') {
                    return ['boolean']
                }
                return []
            })
        if (primitiveTypes.length > 0) {
            return { $types: [...new Set(primitiveTypes)].sort() }
        }
    }

    if (def?.type === 'string') {
        return { $type: 'string' }
    }
    if (def?.type === 'number') {
        return { $type: 'integer' }
    }
    if (def?.type === 'boolean') {
        return { $type: 'boolean' }
    }

    return { $type: 'unknown' }
}

function normalizePropertyTree(tree: unknown): unknown {
    if (!tree || typeof tree !== 'object' || Array.isArray(tree)) {
        return tree
    }

    if ('$types' in tree && Array.isArray(tree.$types)) {
        const normalizedTypes = [...new Set(tree.$types.map((type) => (type === 'number' ? 'integer' : type)))].sort()
        return { $types: normalizedTypes }
    }

    return Object.fromEntries(Object.entries(tree).map(([key, value]) => [key, normalizePropertyTree(value)]))
}

describe('widget config schema parity', () => {
    it('frontend zod schemas expose the same top-level keys as backend pydantic', () => {
        for (const [widgetType, expectedKeys] of Object.entries(configPropertyMetadata.configPropertyKeys)) {
            const schema = WIDGET_CONFIG_SCHEMAS[widgetType as keyof typeof WIDGET_CONFIG_SCHEMAS]
            expect(Object.keys(schema.shape).sort()).toEqual([...expectedKeys].sort())
        }
    })

    it('frontend zod schemas match nested OpenAPI property trees', () => {
        for (const [widgetType, expectedTree] of Object.entries(configPropertyMetadata.configPropertyTrees)) {
            const schema = WIDGET_CONFIG_SCHEMAS[widgetType as keyof typeof WIDGET_CONFIG_SCHEMAS]
            expect(normalizePropertyTree(zodPropertyTree(schema))).toEqual(normalizePropertyTree(expectedTree))
        }
    })

    it('shared widget filter entry schema matches OpenAPI tree', () => {
        const widgetFiltersTree = configPropertyMetadata.configPropertyTrees.error_tracking_list.widgetFilters
        expect(normalizePropertyTree(zodPropertyTree(widgetFilterEntrySchema))).toEqual(
            normalizePropertyTree(widgetFiltersTree.$record)
        )
    })
})
