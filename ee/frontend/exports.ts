import { PostHogEE } from '@posthog/ee/types'

import { transformEventToWeb } from './mobile-replay'

const myTestCode = (): void => {
    // eslint-disable-next-line no-console
    console.log('it works!')
}

const postHogEE: PostHogEE = {
    enabled: true,
    myTestCode,
    mobileReplay: {
        transformEventToWeb,
    },
}

export default postHogEE
