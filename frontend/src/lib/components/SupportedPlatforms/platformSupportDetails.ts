import { ReactNode } from 'react'

import { isObject } from 'lib/utils/guards'

import { PlatformSupport } from './types'

export const PLATFORM_LABELS: Record<string, string> = {
    web: 'Web',
    android: 'Android',
    ios: 'iOS',
    reactNative: 'React Native',
    flutter: 'Flutter',
}

export function platformSupportDetails(platform: PlatformSupport | undefined): {
    supportedSinceVersion: string | false
    note: ReactNode | undefined
} {
    return {
        supportedSinceVersion: isObject(platform) && typeof platform?.version === 'string' ? platform.version : false,
        note: isObject(platform) ? platform.note : undefined,
    }
}
