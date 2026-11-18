import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { HedgehogConfig } from '~/types'

import { GravatarStatus, profilePictureLogic } from './profilePictureLogic'

type ImageOutcome = 'load' | 'error'

let imageOutcome: ImageOutcome = 'error'
let requestedUrls: string[] = []

class FakeImage {
    onload: (() => void) | null = null
    onerror: (() => void) | null = null

    set src(value: string) {
        requestedUrls.push(value)
        setTimeout(() => (imageOutcome === 'load' ? this.onload?.() : this.onerror?.()), 0)
    }
}

const HEDGEHOG_AVATAR_CONFIG: HedgehogConfig = {
    version: 2,
    enabled: false,
    use_as_profile: true,
    party_mode_enabled: false,
    actor_options: { id: 'test-hedgehog', skin: 'default', color: 'green', accessories: [] },
}

describe('profilePictureLogic', () => {
    let logic: ReturnType<typeof profilePictureLogic.build>
    const RealImage = window.Image

    beforeAll(() => {
        window.Image = FakeImage as unknown as typeof Image
    })

    afterAll(() => {
        window.Image = RealImage
    })

    beforeEach(() => {
        initKeaTests()
        requestedUrls = []
        logic = profilePictureLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each<[GravatarStatus, ImageOutcome]>([
        ['found', 'load'],
        ['missing', 'error'],
    ])('marks the gravatar as %s when the image fires %s', async (status, outcome) => {
        imageOutcome = outcome
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['checkGravatar', 'setGravatarStatus'])
            .toMatchValues({ gravatarStatus: status, gravatarChecking: false })
    })

    it('does not contact Gravatar when the hedgehog is the profile picture', async () => {
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, hedgehog_config: HEDGEHOG_AVATAR_CONFIG })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['checkGravatar', 'setGravatarStatus'])
            .toMatchValues({ gravatarChecking: false, gravatarStatus: 'unknown', usesHedgehogAsProfilePicture: true })
        expect(requestedUrls).toEqual([])
    })

    it('probes again when the email changes', async () => {
        imageOutcome = 'load'
        logic.mount()
        await expectLogic(logic).toDispatchActions(['setGravatarStatus']).toMatchValues({ gravatarStatus: 'found' })

        imageOutcome = 'error'
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, email: 'someone.else@example.com' })

        await expectLogic(logic)
            .toDispatchActions(['checkGravatar', 'setGravatarStatus'])
            .toMatchValues({ gravatarStatus: 'missing' })
    })

    it('bypasses the browser cache when checking again', async () => {
        imageOutcome = 'load'
        logic.mount()
        await expectLogic(logic).toDispatchActions(['setGravatarStatus'])
        expect(requestedUrls[0]).not.toContain('&_=')

        imageOutcome = 'error'
        logic.actions.recheckGravatar()

        await expectLogic(logic).toMatchValues({ gravatarChecking: true, gravatarStatus: 'found' })
        await expectLogic(logic)
            .toDispatchActions(['setGravatarStatus'])
            .toMatchValues({ gravatarChecking: false, gravatarStatus: 'missing' })
        expect(requestedUrls[1]).toContain(`&_=${logic.values.gravatarRefreshKey}`)
    })
})
