import { PostHogEE } from '@posthog/ee/types'

import { transformEventToWeb, transformToWeb } from './mobile-replay'

export default async (): Promise<PostHogEE> =>
    Promise.resolve({
        enabled: true,
        mobileReplay: {
            transformEventToWeb,
            transformToWeb,
        },
    })
