import { LemonTag } from '@posthog/lemon-ui'
import { capitalizeFirstLetter } from 'lib/utils'

import { HogFunctionTemplateStatus } from '~/types'

export function DestinationTag({ status }: { status: HogFunctionTemplateStatus }): JSX.Element | null {
    switch (status) {
        case 'alpha':
            return <LemonTag type="danger">Experimental</LemonTag>
        case 'beta':
            return <LemonTag type="completion">Beta</LemonTag>
        case 'stable':
            return <LemonTag type="highlight">New</LemonTag> // Once Hog Functions are fully released we can remove the new label
        default:
            return status ? <LemonTag type="highlight">{capitalizeFirstLetter(status)}</LemonTag> : null
    }
}
