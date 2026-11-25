import { ApiConfig } from 'lib/api'

import { aiObservabilityPeopleRetrieve } from '../../generated/api'
import type { PersonListItemApi } from '../../generated/api.schemas'

export interface PersonRange {
    date_from: string
    date_to?: string
    filter_test_accounts: boolean
    properties?: string
}

export function personRange(dateFrom: string, dateTo: string | null, filterTestAccounts: boolean): PersonRange {
    return { date_from: dateFrom, date_to: dateTo ?? undefined, filter_test_accounts: filterTestAccounts }
}

/** A person's row in the range, anonymous or not. The read fails as not found when the range does not hold them. */
export function readPerson(personId: string, range: PersonRange): Promise<PersonListItemApi> {
    return aiObservabilityPeopleRetrieve(String(ApiConfig.getCurrentProjectId()), personId, range)
}
