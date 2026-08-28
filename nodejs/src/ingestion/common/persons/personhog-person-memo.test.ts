import { DateTime } from 'luxon'

import { InternalPerson } from '~/types'

import { PersonhogPersonMemo } from './personhog-person-memo'

describe('PersonhogPersonMemo', () => {
    let person: InternalPerson
    let memo: PersonhogPersonMemo
    let pendingLanes: Set<string>
    let writesInFlight: Set<string>

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
        // The store's three collaborators, reduced to what a memo test can
        // steer: which persons hold unflushed ops, and which have a write on
        // the wire. Projection is the identity, since no lane holds ops.
        pendingLanes = new Set()
        writesInFlight = new Set()
        memo = new PersonhogPersonMemo(
            (personKey) => pendingLanes.has(personKey),
            (_personKey, document) => document,
            (personKey) => writesInFlight.has(personKey)
        )
    })

    describe('stamp and mark retention', () => {
        it('holds a floor past the watermark for the detection window', () => {
            jest.useFakeTimers()
            try {
                // A floor also refuses fresh reads served inside a deposed
                // leader's detection window, which is a wall-clock bound; a
                // floor swept at a quiet watermark would under-live it.
                memo.beginRead(1, 0, ['1:d1'])
                memo.dropBaseline('1:7', 5)
                memo.releaseBatch(0)

                memo.offerBaseline('1:7', { ...person, version: 3 }, 'leader-read')
                expect(memo.hasBaseline('1:7')).toBe(false)

                jest.advanceTimersByTime(61 * 1000)
                memo.beginRead(1, 1, ['1:d2'])
                memo.releaseBatch(1)
                memo.offerBaseline('1:7', { ...person, version: 3 }, 'leader-read')
                expect(memo.hasBaseline('1:7')).toBe(true)
            } finally {
                jest.useRealTimers()
            }
        })

        it('forgets read stamps at the watermark but holds destroyed marks for the replay window', () => {
            jest.useFakeTimers()
            try {
                memo.beginRead(1, 0, ['1:d1'])
                memo.bumpId('1:d1')
                memo.markDestroyed('1:9')
                expect(memo.versionOf('1:d1')).toBe(1)

                memo.releaseBatch(0)

                // The destroyed mark must outlive the read-stamp watermark:
                // a recorded merge verdict replays in an arbitrarily later
                // batch, and sweeping the mark with the stamps would let
                // that replay resurrect the destroyed person.
                expect(memo.versionOf('1:d1')).toBe(0)
                expect(memo.isDestroyed('1:9')).toBe(true)

                // Once the saga's op retention has passed, no replay can
                // arrive, and the mark goes with the next sweep.
                jest.advanceTimersByTime(26 * 60 * 60 * 1000)
                memo.beginRead(1, 1, ['1:d2'])
                memo.releaseBatch(1)
                expect(memo.isDestroyed('1:9')).toBe(false)
            } finally {
                jest.useRealTimers()
            }
        })

        it('keeps a stamp a still-open batch could be comparing against', () => {
            memo.beginRead(1, 0, ['1:d1'])
            memo.beginRead(1, 1, ['1:d2'])
            memo.bumpId('1:d1')
            memo.markDestroyed('1:9')

            memo.releaseBatch(0)

            // Batch 1 is still running, so a read it issued before the merge
            // can still be on the wire. Clearing here would let that read
            // record an answer the merge already superseded.
            expect(memo.versionOf('1:d1')).toBe(1)
            expect(memo.isDestroyed('1:9')).toBe(true)
        })

        it('a batch that has read but recorded nothing still holds the stamps open', () => {
            // Batch 1's first read is on the wire: a handle is open but not
            // one resolution has been recorded, so any liveness signal keyed
            // on recorded state cannot see it.
            memo.beginRead(1, 0, ['1:d0'])
            memo.beginRead(1, 1, ['1:d1'])
            memo.bumpId('1:d1')
            memo.markDestroyed('1:9')

            memo.releaseBatch(0)

            // Sweeping here would let batch 1's read return, compare against
            // nothing, and record the pre-merge answer the stamp exists to
            // refuse — a destroyed person back as the live answer.
            expect(memo.versionOf('1:d1')).toBe(1)
            expect(memo.isDestroyed('1:9')).toBe(true)
        })

        it('sweeps stamps under continuous batch overlap once their readers are gone', () => {
            memo.beginRead(1, 0, ['1:d1'])
            memo.bumpId('1:d1')
            // A newer batch opens before the older one releases — the shape
            // of a busy pod, where a moment with zero open batches may never
            // come. The stamp's readers all belong to batch 0.
            memo.beginRead(1, 5, ['1:d2'])
            memo.recordResolution(5, '1:d2', '1:7')

            memo.releaseBatch(0)

            // Waiting for full quiescence would keep this entry for the
            // process lifetime; its horizon says batch 0 was the last reader
            // that could hold the pre-bump value, and batch 0 is gone.
            expect(memo.versionOf('1:d1')).toBe(0)
            memo.releaseBatch(5)
        })
    })

    describe('version floors', () => {
        it('a dropped baseline refuses reads below what its dropper knew the leader held', () => {
            memo.offerBaseline('1:7', { ...person, version: 2 }, 'leader-read')
            memo.dropBaseline('1:7', 7)

            // A read issued before the drop answers the state the drop was
            // performed to retire; absence must not let it fill.
            memo.offerBaseline('1:7', { ...person, version: 5 }, 'leader-read')
            expect(memo.hasBaseline('1:7')).toBe(false)

            memo.offerBaseline('1:7', { ...person, version: 7 }, 'leader-read')
            expect(memo.viewOfPerson('1:7')?.version).toBe(7)
        })

        it('a dropped baseline refuses a fill below the floor too', () => {
            // The fill arm is absence-only, and a floored drop is exactly a
            // curated absence: a late prefetch response predating the drop
            // must not fill it, or the update class serves pre-write state.
            memo.recordResolution(0, '1:d1', '1:7')
            memo.dropBaseline('1:7', 7)

            memo.record(1, 'd1', { ...person, version: 5 }, 0, { readClass: 'update', fillOnly: true })
            expect(memo.hasBaseline('1:7')).toBe(false)

            memo.record(1, 'd1', { ...person, version: 7 }, 0, { readClass: 'update', fillOnly: true })
            expect(memo.viewOfPerson('1:7')?.version).toBe(7)
        })

        it('a stale answer cannot refill a floored absence', () => {
            // A drop recorded that the leader moved past version 7;
            // installing an older document leader-backed would arm the
            // no-change filter against state the leader has replaced.
            memo.dropBaseline('1:7', 7)

            memo.offerBaseline('1:7', { ...person, version: 5, properties: { plan: 'frozen' } }, 'own-write')
            expect(memo.hasBaseline('1:7')).toBe(false)

            memo.offerBaseline('1:7', { ...person, version: 7 }, 'own-write')
            expect(memo.viewOfPerson('1:7')?.version).toBe(7)
        })

        it('a late own-write answer cannot refill a floored absence either', () => {
            // The lane and the diff update are independent writers; one's
            // drop can record that the leader moved past what the other's
            // late answer carries.
            memo.dropBaseline('1:7', 7)

            memo.offerBaseline('1:7', { ...person, version: 5 }, 'own-write')
            expect(memo.hasBaseline('1:7')).toBe(false)

            memo.offerBaseline('1:7', { ...person, version: 7 }, 'own-write')
            expect(memo.viewOfPerson('1:7')?.version).toBe(7)
        })

        it('a null write answer on an absence still advances the standing floor', () => {
            // The applied write moved the leader past whatever the floor
            // recorded, even with no document to anchor a new one on.
            memo.dropBaseline('1:7', 5)
            memo.raiseFloorPastAppliedWrite('1:7')

            memo.offerBaseline('1:7', { ...person, version: 5 }, 'leader-read')
            expect(memo.hasBaseline('1:7')).toBe(false)

            memo.offerBaseline('1:7', { ...person, version: 6 }, 'leader-read')
            expect(memo.viewOfPerson('1:7')?.version).toBe(6)
        })

        it('dropping behind writes floors at the best proof either side carries', () => {
            // Writes past the standing document: dropped, floored at the
            // writes' version, so only provably stale deliveries are refused.
            memo.offerBaseline('1:20', { ...person, id: '20', version: 7 }, 'own-write')
            memo.dropBaselineBehindWrites('1:20', 8)
            expect(memo.viewOfPerson('1:20')).toBeNull()
            memo.offerBaseline('1:20', { ...person, id: '20', version: 7 }, 'leader-read')
            expect(memo.viewOfPerson('1:20')).toBeNull()
            memo.offerBaseline('1:20', { ...person, id: '20', version: 8 }, 'leader-read')
            expect(memo.viewOfPerson('1:20')).toMatchObject({ version: 8 })

            // Writes that answered no document: the standing document's own
            // version is the best proof of what the leader reached.
            memo.offerBaseline('1:21', { ...person, id: '21', version: 10 }, 'own-write')
            memo.dropBaselineBehindWrites('1:21', undefined)
            expect(memo.viewOfPerson('1:21')).toBeNull()
            memo.offerBaseline('1:21', { ...person, id: '21', version: 9 }, 'leader-read')
            expect(memo.viewOfPerson('1:21')).toBeNull()
            memo.offerBaseline('1:21', { ...person, id: '21', version: 10 }, 'leader-read')
            expect(memo.viewOfPerson('1:21')).toMatchObject({ version: 10 })
        })
    })

    describe('baseline provenance', () => {
        it('a replayed survivor below the baseline keeps the newer answer', () => {
            memo.offerBaseline('1:7', { ...person, version: 6 }, 'own-write')

            // A second writer's answer delivered late is behind the leader.
            memo.offerBaseline('1:7', { ...person, version: 4, properties: { plan: 'replayed' } }, 'own-write')

            expect(memo.viewOfPerson('1:7')?.version).toBe(6)
        })

        it('a late own-write answer cannot roll the view back across a newer one', () => {
            // Two independent writers' answers can be delivered inverted;
            // installing the earlier over the later would revive replaced
            // state and let a later matching event be filtered into a lost
            // write.
            memo.offerBaseline('1:7', { ...person, version: 3, properties: { k: 'newer' } }, 'own-write')
            memo.offerBaseline('1:7', { ...person, version: 2, properties: { k: 'older' } }, 'own-write')

            expect(memo.viewOfPerson('1:7')?.properties).toEqual({ k: 'newer' })
        })

        it('marking a person destroyed drops the baseline a sibling id left standing', () => {
            // The mark refuses every future install, so a document left
            // behind would serve the dead person for the rest of the batch
            // with nothing able to replace it.
            memo.offerBaseline('1:30', { ...person, id: '30', version: 3 }, 'leader-read')
            memo.markDestroyed('1:30')
            expect(memo.hasBaseline('1:30')).toBe(false)
        })
    })

    describe('batch references', () => {
        it('a prefetch response landing after its batch released claims no reference', () => {
            // Two batches name the id, so batch 0 releasing leaves the edge
            // standing. The prefetch batch 0 fired is still in flight.
            memo.recordResolution(0, '1:d1', '1:7')
            memo.recordResolution(1, '1:d1', '1:7')
            memo.releaseBatch(0)
            expect(memo.resolutionOf('1:d1')).toBe('1:7')

            memo.record(1, 'd1', person, 0, { readClass: 'update', fillOnly: true })
            // It may still repair a document hole; what it may not do is
            // claim a reference for a batch that has gone.
            expect(memo.viewOfPerson('1:7')).toMatchObject({ id: '7' })

            memo.releaseBatch(1)

            // A reference claimed for batch 0 would make every later release
            // see the key as held elsewhere, so the resolution and the
            // projection behind it would never be freed.
            expect(memo.resolutionOf('1:d1')).toBeUndefined()
            expect(memo.baselineCount).toBe(0)
        })
    })
})
