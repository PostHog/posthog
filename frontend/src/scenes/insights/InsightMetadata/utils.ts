import { DashboardItemType } from '~/types'
import { ensureStringIsNotBlank } from 'lib/utils'

export function cleanMetadataValues(insight: Partial<DashboardItemType>): Partial<DashboardItemType> {
    return Object.fromEntries(
        Object.entries(insight).map(([k, v]) => [k, (typeof v === 'string' ? ensureStringIsNotBlank(v) : v) ?? null])
    )
}
