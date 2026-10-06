import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagCallsGroups } from 'lib/components/TaxonomicFilter/utils/featureFlagCallsGroup'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'

describe('featureFlagCallsGroups', () => {
    // hiddenEvents.test.ts covers every mode. These cases cover the wiring to the hidden event.
    it('offers the group when the picker hides $feature_flag_called', () => {
        expect(featureFlagCallsGroups(FlagEvaluationsModeEnumApi.Number1).map((group) => group.type)).toEqual([
            TaxonomicFilterGroupType.FeatureFlagCalls,
        ])
    })

    it.each([
        ['the team is on the Events mode', FlagEvaluationsModeEnumApi.Number0, undefined],
        ['the picker shows hidden events', FlagEvaluationsModeEnumApi.Number1, true],
    ])('offers nothing when %s', (_label, mode, includeHiddenEvents) => {
        expect(featureFlagCallsGroups(mode, includeHiddenEvents)).toEqual([])
    })

    it.each([
        ['an empty search', '', true],
        // The picker hides this event. The docs send users to it by these names.
        ['the hidden event name', '$feature_flag_called', true],
        ['the hidden event name without its $', 'feature_flag_called', true],
        ['the hidden event label', 'Feature flag called', true],
        ['part of the entry label', ' flag CALL ', true],
        ['an unrelated search', 'pageview', false],
    ])('matches %s', (_label, query, matches) => {
        const [group] = featureFlagCallsGroups(FlagEvaluationsModeEnumApi.Number1)
        const items = (group.options ?? []) as TaxonomicDefinitionTypes[]
        expect(group.localItemsSearch?.(items, query)).toEqual(matches ? items : [])
    })
})
