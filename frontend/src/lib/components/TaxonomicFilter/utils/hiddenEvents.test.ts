import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    hiddenEventMatchingSearch,
    hiddenEventNames,
    withHiddenEventsExcluded,
} from 'lib/components/TaxonomicFilter/utils/hiddenEvents'
import { FEATURE_FLAGS } from 'lib/constants'

const FLAG_ON = { [FEATURE_FLAGS.HIDE_EVENTS_IN_QUERY_BUILDERS]: true }
const FLAG_OFF = {}

describe('events hidden from query builders', () => {
    // The whole feature keys off this taxonomy entry.
    it('hides $feature_flag_called while the kill switch is on', () => {
        expect(hiddenEventNames(FLAG_ON)).toContain('$feature_flag_called')
    })

    it.each([
        ['the kill switch is off', FLAG_OFF, undefined],
        // Pickers that read live event data, and the experiment exposure pickers, opt back in.
        ['the picker opts out', FLAG_ON, true],
    ])('hides nothing when %s', (_label, featureFlags, includeHiddenEvents) => {
        expect(hiddenEventNames(featureFlags, includeHiddenEvents)).toEqual([])
    })

    describe('withHiddenEventsExcluded', () => {
        // Cohort pickers exclude "All events" as null, so appending must not replace what came in.
        it('adds the hidden names to the Events group and keeps the ones the caller passed', () => {
            const merged = withHiddenEventsExcluded({ [TaxonomicFilterGroupType.Events]: [null] }, FLAG_ON)
            expect(merged?.[TaxonomicFilterGroupType.Events]).toEqual([null, '$feature_flag_called'])
        })

        it('leaves the record alone while the kill switch is off', () => {
            const merged = withHiddenEventsExcluded({ [TaxonomicFilterGroupType.Events]: [null] }, FLAG_OFF)
            expect(merged?.[TaxonomicFilterGroupType.Events]).toEqual([null])
        })
    })

    describe('hiddenEventMatchingSearch', () => {
        const EXCLUDED = [null, '$feature_flag_called']

        it.each([
            ['the name as typed', '$feature_flag_called', EXCLUDED, '$feature_flag_called'],
            ['the name with stray case and spacing', '  $FEATURE_FLAG_CALLED ', EXCLUDED, '$feature_flag_called'],
            // Lists render core events by label, so this is the other string a user may type.
            ['the label lists show', 'Feature flag called', EXCLUDED, '$feature_flag_called'],
            // A substring rule would claim this, and "feature" is a search someone really makes.
            ['a word the name merely contains', 'feature', EXCLUDED, null],
            // Someone could legitimately want to create an event under this name.
            ['the name without its $', 'feature_flag_called', EXCLUDED, null],
            // The picker opted in, so it is hiding nothing and has nothing to explain.
            ['a picker excluding nothing', '$feature_flag_called', [null], null],
            ['a group with no exclusions', '$feature_flag_called', undefined, null],
            ['an empty search', '   ', EXCLUDED, null],
        ])('matches %s', (_label, searchQuery, excluded, expected) => {
            expect(hiddenEventMatchingSearch(searchQuery, excluded)).toBe(expected)
        })

        // Two derivations off the same taxonomy scan. If they disagree, a picker hides an event it
        // then refuses to explain.
        it('recognizes every name the Events group hides', () => {
            for (const name of hiddenEventNames(FLAG_ON)) {
                expect(hiddenEventMatchingSearch(name, [name])).toBe(name)
            }
        })
    })
})
