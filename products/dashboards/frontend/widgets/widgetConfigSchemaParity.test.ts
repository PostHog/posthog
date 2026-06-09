// Guards FE Zod config shape against backend/OpenAPI pydantic drift (cheap SSOT check).
import { z, type ZodTypeAny } from 'zod'

import configPropertyMetadata from '../generated/widget-config-property-keys.json'
import {
    errorTrackingWidgetConfigSchema,
    sessionReplayWidgetConfigSchema,
    widgetFilterEntrySchema,
} from '../generated/widget-configs.zod'

const WIDGET_CONFIG_SCHEMAS = {
    error_tracking_list: errorTrackingWidgetConfigSchema,
    session_replay_list: sessionReplayWidgetConfigSchema,
} as const

type ZodDef = {
    type?: string
    innerType?: ZodTypeAny
    options?: readonly ZodTypeAny[]
    valueType?: ZodTypeAny
    element?: ZodTypeAny
}

function zodDef(schema: ZodTypeAny): ZodDef | undefined {
    return (schema as { _zod?: { def?: ZodDef } })._zod?.def
}

function unwrapZod(schema: ZodTypeAny): ZodTypeAny {
    let current = schema
    // eslint-disable-next-line no-constant-condition
    while (true) {
        const def = zodDef(current)
        if (def?.type === 'optional' || def?.type === 'nullable' || def?.type === 'default') {
            current = def.innerType ?? current
            continue
        }
        if (current instanceof z.ZodOptional || current instanceof z.ZodNullable) {
            current = current.unwrap()
            continue
        }
        if (current instanceof z.ZodDefault) {
            current = current.removeDefault()
            continue
        }
        break
    }
    return current
}

function zodPropertyTree(schema: ZodTypeAny): unknown {
    const unwrapped = unwrapZod(schema)
    const def = zodDef(unwrapped)

    if (unwrapped instanceof z.ZodObject || def?.type === 'object') {
        const shape = unwrapped.shape
        return Object.fromEntries(
            Object.entries(shape).map(([key, value]) => [key, zodPropertyTree(value as ZodTypeAny)])
        )
    }

    if (unwrapped instanceof z.ZodRecord || def?.type === 'record') {
        const valueType = def?.valueType ?? (unwrapped as z.ZodRecord).valueSchema
        return {
            $record: zodPropertyTree(valueType as ZodTypeAny),
        }
    }

    if (unwrapped instanceof z.ZodArray || def?.type === 'array') {
        const element = def?.element ?? (unwrapped as z.ZodArray).element
        return {
            $array: zodPropertyTree(element as ZodTypeAny),
        }
    }

    if (unwrapped instanceof z.ZodEnum || def?.type === 'enum') {
        const options =
            def && 'entries' in def && def.entries
                ? Object.keys(def.entries as Record<string, unknown>)
                : (unwrapped as z.ZodEnum<[string, ...string[]]>).options
        return { $enum: [...options].sort() }
    }

    if (unwrapped instanceof z.ZodUnion || def?.type === 'union') {
        const options = def?.options ?? (unwrapped as z.ZodUnion<[ZodTypeAny, ...ZodTypeAny[]]>).options
        const substantiveOptions = options.filter(
            (option) => zodDef(unwrapZod(option))?.type !== 'null' && !(unwrapZod(option) instanceof z.ZodNull)
        )
        if (substantiveOptions.length === 1) {
            return zodPropertyTree(substantiveOptions[0] as ZodTypeAny)
        }
        const objectArm = substantiveOptions.find(
            (option) =>
                unwrapZod(option as ZodTypeAny) instanceof z.ZodObject ||
                zodDef(unwrapZod(option as ZodTypeAny))?.type === 'object'
        )
        if (objectArm) {
            return zodPropertyTree(objectArm as ZodTypeAny)
        }
        const enumArm = substantiveOptions.find(
            (option) =>
                unwrapZod(option as ZodTypeAny) instanceof z.ZodEnum ||
                zodDef(unwrapZod(option as ZodTypeAny))?.type === 'enum'
        )
        if (enumArm) {
            return zodPropertyTree(enumArm as ZodTypeAny)
        }
        const hasStringArm = substantiveOptions.some((option) => {
            const unwrappedOption = unwrapZod(option as ZodTypeAny)
            return unwrappedOption instanceof z.ZodString || zodDef(unwrappedOption)?.type === 'string'
        })
        const hasArrayArm = substantiveOptions.some((option) => {
            const unwrappedOption = unwrapZod(option as ZodTypeAny)
            return unwrappedOption instanceof z.ZodArray || zodDef(unwrappedOption)?.type === 'array'
        })
        if (hasStringArm && hasArrayArm) {
            return { $types: ['string'] }
        }

        const primitiveTypes = substantiveOptions
            .map((option) => unwrapZod(option as ZodTypeAny))
            .flatMap((option) => {
                const optionDef = zodDef(option)
                if (option instanceof z.ZodString || optionDef?.type === 'string') {
                    return ['string']
                }
                if (option instanceof z.ZodNumber || optionDef?.type === 'number') {
                    return ['integer']
                }
                if (option instanceof z.ZodBoolean || optionDef?.type === 'boolean') {
                    return ['boolean']
                }
                return []
            })
        if (primitiveTypes.length > 0) {
            return { $types: [...new Set(primitiveTypes)].sort() }
        }
    }

    if (unwrapped instanceof z.ZodString || def?.type === 'string') {
        return { $type: 'string' }
    }
    if (unwrapped instanceof z.ZodNumber || def?.type === 'number') {
        return { $type: 'integer' }
    }
    if (unwrapped instanceof z.ZodBoolean || def?.type === 'boolean') {
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
