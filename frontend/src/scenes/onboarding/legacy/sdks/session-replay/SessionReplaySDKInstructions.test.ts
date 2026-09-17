import { SDKKey } from '~/types'

import { getAvailableSDKs } from '../getAvailableSDKs'
import { SessionReplaySDKDocsLinkOverrides, SessionReplaySDKInstructions } from './SessionReplaySDKInstructions'

describe('SessionReplaySDKInstructions', () => {
    it('makes Unity selectable with session replay instructions and docs', () => {
        const availableSDKs = getAvailableSDKs(SessionReplaySDKInstructions, {}, SessionReplaySDKDocsLinkOverrides)
        const unitySDK = availableSDKs.find(({ key }) => key === SDKKey.UNITY)

        expect(SessionReplaySDKInstructions[SDKKey.UNITY]).not.toBeUndefined()
        expect(unitySDK).toMatchObject({
            key: SDKKey.UNITY,
            docsLink: 'https://posthog.com/docs/session-replay/installation/unity',
        })
    })
})
