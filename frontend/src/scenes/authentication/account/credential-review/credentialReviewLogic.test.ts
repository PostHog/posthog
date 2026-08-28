import { passkeySettingsLogic } from 'scenes/settings/user/passkeySettingsLogic'
import { personalAPIKeysLogic } from 'scenes/settings/user/personalAPIKeysLogic'

import { initKeaTests } from '~/test/init'

import { credentialReviewLogic } from './credentialReviewLogic'

describe('credentialReviewLogic', () => {
    let logic: ReturnType<typeof credentialReviewLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = credentialReviewLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('mounts without pulling in the credential list logics', () => {
        // sceneLogic mounts this logic before the review component renders. It must not
        // load or mount personalAPIKeysLogic or passkeySettingsLogic on mount, or a throw
        // during their mount becomes a 404 for the whole screen. The component mounts and
        // loads those logics instead.
        logic.mount()

        expect(personalAPIKeysLogic.isMounted()).toBe(false)
        expect(passkeySettingsLogic.isMounted()).toBe(false)
    })
})
