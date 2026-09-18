import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'

import { QueryContext } from '~/queries/types'

import { aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
import { AIObservabilityInstrumentationCheckEnumApi, InstrumentationCheckApi } from '../generated/api.schemas'
import { instrumentationChecklistLogic } from '../instrumentationChecklist/instrumentationChecklistLogic'

export type InstrumentationEmptyState = Pick<QueryContext, 'emptyStateHeading' | 'emptyStateDetail'>

/** The check a tab may blame its empty state on, or null when the tab keeps its generic copy. */
export function useInstrumentationWarning(
    check: AIObservabilityInstrumentationCheckEnumApi
): InstrumentationCheckApi | null {
    const { warningForCheck, windowDays } = useValues(instrumentationChecklistLogic)
    const { instrumentationVerdictApplies } = useValues(aiObservabilitySharedLogic)

    return instrumentationVerdictApplies(windowDays) ? warningForCheck(check) : null
}

/** The same verdict shaped for a `DataTable`, ready to spread into its `QueryContext`. */
export function useInstrumentationEmptyState(
    check: AIObservabilityInstrumentationCheckEnumApi,
    heading: string
): InstrumentationEmptyState | null {
    const warning = useInstrumentationWarning(check)

    if (!warning) {
        return null
    }

    return {
        emptyStateHeading: heading,
        // `emptyStateHeading` is string-only, so the docs link has to ride along in the detail.
        emptyStateDetail: (
            <>
                {warning.detail} <Link to={warning.docs_url}>Learn more</Link>
            </>
        ),
    }
}
