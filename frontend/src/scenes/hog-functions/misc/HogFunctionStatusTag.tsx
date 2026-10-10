import { LemonTag } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'

import { HogFunctionTemplateStatus, HogFunctionTypeType } from '~/types'

export const DESTINATION_TYPES: HogFunctionTypeType[] = [
    'destination',
    'site_destination',
    'internal_destination',
    'legacy_destination',
]

export interface HogFunctionStatusTagProps {
    status: HogFunctionTemplateStatus
    type: HogFunctionTypeType
}

export function HogFunctionStatusTag({ status, type }: HogFunctionStatusTagProps): JSX.Element | null {
    // We fully support every destination we offer, so release stage labels do not apply to them
    if (DESTINATION_TYPES.includes(type) && (status === 'alpha' || status === 'beta')) {
        return null
    }

    switch (status) {
        case 'alpha':
            return <LemonTag type="danger">Experimental</LemonTag>
        case 'beta':
            return <LemonTag type="completion">Beta</LemonTag>
        case 'stable':
            return null
        case 'coming_soon':
            return <LemonTag type="muted">Roadmap</LemonTag>
        case 'hidden':
            return <LemonTag type="muted">Hidden</LemonTag>
        default:
            return status ? <LemonTag type="highlight">{capitalizeFirstLetter(status)}</LemonTag> : null
    }
}
