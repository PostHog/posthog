import { IncrementalField, IncrementalFieldType } from '~/types'

import { resolveIncrementalField } from './incrementalField'

const field = (name: string, type: IncrementalFieldType = 'timestamp'): IncrementalField => ({
    label: name,
    type,
    field: name,
    field_type: type,
})

describe('resolveIncrementalField', () => {
    it('prefers an updated_at column over created_at', () => {
        const resolved = resolveIncrementalField([field('created_at'), field('updated_at')])
        expect(resolved?.field).toBe('updated_at')
    })

    it('falls back to created_at when no updated column exists', () => {
        const resolved = resolveIncrementalField([field('created_at')])
        expect(resolved?.field).toBe('created_at')
    })

    it.each([
        ['a bare date column', [field('date_of_birth', 'date')]],
        ['an unrelated integer column', [field('priority', 'integer')]],
        ['a timestamp without update semantics', [field('last_seen', 'timestamp')]],
    ])('leaves the field unset for %s', (_label, fields) => {
        expect(resolveIncrementalField(fields)).toBeUndefined()
    })

    it('does not use a detected primary key for an incremental (merge) sync', () => {
        const resolved = resolveIncrementalField([field('id', 'integer')], {
            syncType: 'incremental',
            detectedPrimaryKeys: ['id'],
        })
        expect(resolved).toBeUndefined()
    })

    it('uses a detected integer primary key as the cursor for an append sync', () => {
        const resolved = resolveIncrementalField([field('id', 'integer'), field('priority', 'integer')], {
            syncType: 'append',
            detectedPrimaryKeys: ['id'],
        })
        expect(resolved?.field).toBe('id')
    })

    it('ignores a non-integer detected primary key for an append sync', () => {
        const resolved = resolveIncrementalField([field('uuid', 'date')], {
            syncType: 'append',
            detectedPrimaryKeys: ['uuid'],
        })
        expect(resolved).toBeUndefined()
    })
})
