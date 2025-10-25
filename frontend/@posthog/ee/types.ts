// NOTE: All exported items from the EE module _must_ be optionally defined to ensure we work well with FOSS
import { eventWithTime } from '@posthog/rrweb-types'

export type PostHogEE = {
    enabled: boolean
    mobileReplay?: {
        transformEventToWeb(x: unknown, validateTransformation?: boolean): eventWithTime | null
        transformToWeb(x: unknown[]): eventWithTime[]
    }
}
