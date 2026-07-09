import { describe, expect, it } from 'vitest'

import { SPEC_SCHEMA_SECTIONS, specJsonSchema } from './spec-json-schema'

describe('specJsonSchema', () => {
    it('emits the full inlined spec schema (no $defs) with rich descriptions', () => {
        const result = specJsonSchema()
        expect(result).not.toBeNull()
        expect(result?.section).toBeNull()
        const schema = result?.spec_json_schema as Record<string, any>
        // Inlined (no $ref/$defs) so every slice is self-contained.
        expect(schema.$defs).toBeUndefined()
        expect(Object.keys(schema.properties)).toEqual(SPEC_SCHEMA_SECTIONS)
        // Descriptions migrated into zod `.describe()` travel through to the schema.
        expect(typeof schema.properties.models.description).toBe('string')
    })

    it('emits the write/input shape — defaulted fields are optional', () => {
        const schema = specJsonSchema()?.spec_json_schema as Record<string, any>
        // Every top-level field has a zod default, so none are required on write.
        expect(schema.required).toBeUndefined()
        // Inside the auto policy only `mode` is required (level/optimize_for default).
        expect(schema.properties.models.oneOf[0].required).toEqual(['mode'])
    })

    it('slices one section, self-contained with its own $schema', () => {
        const result = specJsonSchema('models')
        expect(result?.section).toBe('models')
        const slice = result?.spec_json_schema as Record<string, any>
        expect(slice.$schema).toBeTruthy()
        expect(slice.oneOf).toHaveLength(2) // auto | manual
    })

    it('returns null for an unknown section', () => {
        expect(specJsonSchema('nope')).toBeNull()
    })

    it('exposes every top-level spec field as a section', () => {
        expect(SPEC_SCHEMA_SECTIONS).toEqual(
            expect.arrayContaining(['models', 'triggers', 'tools', 'mcps', 'skills', 'secrets', 'limits'])
        )
    })
})
