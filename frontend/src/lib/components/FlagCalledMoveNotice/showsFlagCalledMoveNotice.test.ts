import { showsFlagCalledMoveNotice } from 'lib/components/FlagCalledMoveNotice/showsFlagCalledMoveNotice'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'

const { Events, EventProperties } = TaxonomicFilterGroupType
const {
    Number0: EVENTS_MODE,
    Number1: READS_FLAG_EVALUATIONS,
    Number2: FLAG_EVALUATIONS_ONLY,
} = FlagEvaluationsModeEnumApi

describe('showsFlagCalledMoveNotice', () => {
    it.each([
        ['the team is on the Events mode', EVENTS_MODE],
        ['no team is loaded', undefined],
    ])('shows the notice on the flag called event when %s', (_label, mode) => {
        expect(showsFlagCalledMoveNotice('$feature_flag_called', Events, mode)).toBe(true)
    })

    it.each([
        // These modes read flag calls from flag_evaluations, where the event keeps working.
        ['the team reads flag evaluations', '$feature_flag_called', Events, READS_FLAG_EVALUATIONS],
        ['the team writes only flag evaluations', '$feature_flag_called', Events, FLAG_EVALUATIONS_ONLY],
        ['the event is another event', '$pageview', Events, EVENTS_MODE],
        ['the name is not an event', '$feature_flag_called', EventProperties, EVENTS_MODE],
    ])('hides the notice when %s', (_label, name, groupType, mode) => {
        expect(showsFlagCalledMoveNotice(name, groupType, mode)).toBe(false)
    })
})
