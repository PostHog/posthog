import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    hiddenEventMatchingSearch,
    hiddenEventNames,
    withHiddenEventsExcluded,
} from 'lib/components/TaxonomicFilter/utils/hiddenEvents'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'

describe('events hidden from query builders', () => {
    // The mode gate belongs to the flag evaluations rollout. A second event marked
    // hidden_in_query_builders fails this test until it gets its own gate.
    it.each([
        ['reads flag evaluations', FlagEvaluationsModeEnumApi.Number1],
        ['writes only flag evaluations', FlagEvaluationsModeEnumApi.Number2],
    ])('hides $feature_flag_called for a team that %s', (_label, mode) => {
        expect(hiddenEventNames(mode)).toEqual(['$feature_flag_called'])
    })

    it.each([
        ['the team is on the Events mode', FlagEvaluationsModeEnumApi.Number0, undefined],
        ['the team has no mode', undefined, undefined],
        // Pickers that read live event data, and the experiment exposure pickers, opt back in.
        ['the picker opts out', FlagEvaluationsModeEnumApi.Number1, true],
    ])('hides nothing when %s', (_label, mode, includeHiddenEvents) => {
        expect(hiddenEventNames(mode, includeHiddenEvents)).toEqual([])
    })

    describe('withHiddenEventsExcluded', () => {
        // Cohort pickers exclude "All events" as null, so appending must not replace what came in.
        it('adds the hidden names to the Events group and keeps the ones the caller passed', () => {
            const merged = withHiddenEventsExcluded(
                { [TaxonomicFilterGroupType.Events]: [null] },
                FlagEvaluationsModeEnumApi.Number1
            )
            expect(merged?.[TaxonomicFilterGroupType.Events]).toEqual([null, '$feature_flag_called'])
        })

        it('leaves the record alone for a team on the Events mode', () => {
            const merged = withHiddenEventsExcluded(
                { [TaxonomicFilterGroupType.Events]: [null] },
                FlagEvaluationsModeEnumApi.Number0
            )
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
            for (const name of hiddenEventNames(FlagEvaluationsModeEnumApi.Number1)) {
                expect(hiddenEventMatchingSearch(name, [name])).toBe(name)
            }
        })
    })
})
