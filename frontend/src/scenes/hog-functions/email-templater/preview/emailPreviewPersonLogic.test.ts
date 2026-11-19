import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { emailPreviewPersonLogic } from './emailPreviewPersonLogic'

const ADA = ['person-ada', { display_name: 'Ada' }, JSON.stringify({ email: 'ada@example.com' })]
const GRACE = { id: 'person-grace', displayName: 'Grace', properties: { email: 'grace@example.com' } }

describe('emailPreviewPersonLogic', () => {
    let logic: ReturnType<typeof emailPreviewPersonLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.spyOn(api, 'query').mockResolvedValue({ results: [ADA] } as any)
        logic = emailPreviewPersonLogic({ scope: 'test' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPersonsSuccess'])
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('previews a custom person until someone is picked from search', () => {
        logic.actions.setCustomProperties({ first_name: 'Sam' })
        expect(logic.values.previewPerson).toMatchObject({ properties: { first_name: 'Sam' } })

        logic.actions.pickPerson(GRACE)
        expect(logic.values.previewPerson).toEqual(GRACE)
        expect(logic.values.customProperties).toBeNull()
    })
})
