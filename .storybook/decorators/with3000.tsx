import { useMountedLogic } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { useFeatureFlags } from '~/mocks/browser'
import type { DecoratorFn } from '@storybook/react'

/** Activate PostHog 3000. */
export const with3000: DecoratorFn = (Story) => {
    useFeatureFlags([FEATURE_FLAGS.POSTHOG_3000])
    useMountedLogic(themeLogic)
    useEffect(() => {
        document.body.classList.add('posthog-3000')
        return () => {
            document.body.classList.remove('posthog-3000')
        }
    })

    return <Story />
}
