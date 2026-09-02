import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { GravatarStatus, profilePictureLogic } from './profilePictureLogic'

type ImageOutcome = 'load' | 'error'

let imageOutcome: ImageOutcome = 'error'

class FakeImage {
    onload: (() => void) | null = null
    onerror: (() => void) | null = null

    set src(_value: string) {
        setTimeout(() => (imageOutcome === 'load' ? this.onload?.() : this.onerror?.()), 0)
    }
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

    it('keeps the current status while checking again', async () => {
        imageOutcome = 'load'
        logic.mount()
        await expectLogic(logic).toDispatchActions(['setGravatarStatus'])

        imageOutcome = 'error'
        logic.actions.recheckGravatar()

        await expectLogic(logic).toMatchValues({
            gravatarChecking: true,
            gravatarStatus: 'found',
            gravatarRecheckCount: 1,
        })
        await expectLogic(logic)
            .toDispatchActions(['setGravatarStatus'])
            .toMatchValues({ gravatarChecking: false, gravatarStatus: 'missing' })
    })
})
