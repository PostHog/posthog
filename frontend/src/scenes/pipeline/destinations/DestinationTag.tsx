import { LemonTag } from '@posthog/lemon-ui'
import { capitalizeFirstLetter } from 'lib/utils'

import { HogFunctionTemplateStatus } from '~/types'

interface DestinationTagProps {
    status: HogFunctionTemplateStatus
}

export function DestinationTag({ status }: DestinationTagProps): JSX.Element | null {
    switch (status) {
        case 'alpha':
            return <LemonTag type="danger">Experimental</LemonTag>
        case 'beta':
            return <LemonTag type="completion">Beta</LemonTag>
        case 'stable':
            // Once Hog Functions are fully released we can remove the new label
            return <LemonTag type="highlight">New</LemonTag>
        case 'client-side':
            return <LemonTag type="success">Client-Side</LemonTag>
        default:
            return status ? <LemonTag type="highlight">{capitalizeFirstLetter(status)}</LemonTag> : null
    }
}
