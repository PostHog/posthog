// NOTE: All exported items from the EE module _must_ be optionally defined to ensure we work well with FOSS

import { eventWithTime } from '@rrweb/types'

export type PostHogEE = {
    enabled: boolean
    mobileReplay?: {
        // defined as unknown while the mobileEventWithTime type is in the ee folder
        transformEventToWeb(x: unknown): eventWithTime | null
        transformToWeb(x: unknown[]): eventWithTime[]
    }
}
