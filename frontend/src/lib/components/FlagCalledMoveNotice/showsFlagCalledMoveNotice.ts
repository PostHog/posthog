import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'

const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'

// On modes other than Events, flag views read flag calls from flag_evaluations and keep working, so the notice
// would be wrong there.
export function showsFlagCalledMoveNotice(
    name: string | null | undefined,
    groupType: TaxonomicFilterGroupType,
    flagEvaluationsMode: FlagEvaluationsModeEnumApi | undefined
): boolean {
    return (
        name === FEATURE_FLAG_CALLED_EVENT &&
        groupType === TaxonomicFilterGroupType.Events &&
        (flagEvaluationsMode ?? FlagEvaluationsModeEnumApi.Number0) === FlagEvaluationsModeEnumApi.Number0
    )
}
