import { LemonTag } from '@posthog/lemon-ui'

import { LabsTag } from 'lib/lemon-ui/LabsTag'
import { capitalizeFirstLetter } from 'lib/utils'

import { HogFunctionTemplateStatus } from '~/types'

export interface HogFunctionStatusTagProps {
    status: HogFunctionTemplateStatus
}

export function HogFunctionStatusTag({ status }: HogFunctionStatusTagProps): JSX.Element | null {
    switch (status) {
        case 'alpha':
            return <LabsTag stage="alpha" />
        case 'beta':
            return <LabsTag stage="beta" />
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
