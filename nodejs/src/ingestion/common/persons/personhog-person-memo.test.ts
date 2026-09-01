import { DateTime } from 'luxon'

import { InternalPerson } from '~/types'

import { PersonhogPersonMemo } from './personhog-person-memo'

describe('PersonhogPersonMemo', () => {
    let person: InternalPerson
    let memo: PersonhogPersonMemo
    let pendingLanes: Set<string>

    beforeEach(() => {
        person = {
            id: '7',
            uuid: 'person-uuid',
            team_id: 1,
            properties: { plan: 'free' },
            created_at: DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
            is_user_id: null,
            is_identified: false,
            last_seen_at: null,
        }
        // The store's collaborators, reduced to what a memo test can steer:
        // which persons hold unflushed ops. Projection is the identity,
        // since no lane holds ops.
        pendingLanes = new Set()
        memo = new PersonhogPersonMemo(
            (personKey) => pendingLanes.has(personKey),
            (_personKey, document) => document
        )
    })

    describe('newer-wins installs', () => {
        it('a document below the standing baseline cannot replace it', () => {
            // Reads of one person can be delivered out of order; the lower
            // version is the staler read, and installing it would revive
            // replaced state as the batch's live answer.
            memo.offerBaseline('1:7', { ...person, version: 6, properties: { k: 'newer' } })
            memo.offerBaseline('1:7', { ...person, version: 4, properties: { k: 'older' } })

            expect(memo.viewOfPerson('1:7')?.properties).toEqual({ k: 'newer' })
        })

        it('an equal or newer document replaces the baseline', () => {
            memo.offerBaseline('1:7', { ...person, version: 4, properties: { k: 'older' } })
            memo.offerBaseline('1:7', { ...person, version: 6, properties: { k: 'newer' } })

            expect(memo.viewOfPerson('1:7')?.properties).toEqual({ k: 'newer' })
        })
    })

    describe('fill-only records', () => {
        it('supplies a document but claims no reference', () => {
            // Two batches name the id, so batch 0 releasing leaves the edge
            // standing. The prefetch batch 0 fired is still in flight.
            memo.recordResolution(0, '1:d1', '1:7')
            memo.recordResolution(1, '1:d1', '1:7')
            memo.releaseBatch(0)
            expect(memo.resolutionOf('1:d1')).toBe('1:7')

            memo.record(1, 'd1', person, 0, { fillOnly: true })
            // It may still repair a document hole; what it may not do is
            // claim a reference for a batch that has gone.
            expect(memo.viewOfPerson('1:7')).toMatchObject({ id: '7' })

            memo.releaseBatch(1)

            // A reference claimed for batch 0 would make every later release
            // see the key as held elsewhere, so the resolution and the
            // document behind it would never be freed.
            expect(memo.resolutionOf('1:d1')).toBeUndefined()
            expect(memo.baselineCount).toBe(0)
        })

        it('cannot move a standing edge', () => {
            // A merge repointed the id while the prefetch response was on
            // the wire; the response is the older fact and must not repoint
            // the id back.
            memo.recordResolution(0, '1:d1', '1:9')

            memo.record(1, 'd1', person, 0, { fillOnly: true })

            expect(memo.resolutionOf('1:d1')).toBe('1:9')
        })
    })

    describe('liveness', () => {
        it('a pending lane keeps the baseline past its last reference', () => {
            pendingLanes.add('1:7')
            memo.recordResolution(0, '1:d1', '1:7')
            memo.offerBaseline('1:7', person)

            memo.releaseBatch(0)

            // The lane's unsent ops replay over this document; evicting it
            // would lose the read-your-write view they compose.
            expect(memo.hasBaseline('1:7')).toBe(true)
        })

        it('releasing the last reference frees the baseline', () => {
            memo.recordResolution(0, '1:d1', '1:7')
            memo.offerBaseline('1:7', person)

            memo.releaseBatch(0)

            expect(memo.hasBaseline('1:7')).toBe(false)
            expect(memo.baselineCount).toBe(0)
        })
    })
})
