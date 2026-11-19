import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { renderEmailPreview } from './emailPreview'
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
        logic.actions.setCustomProperties({ 'person.properties.first_name': 'Sam', 'event.properties.plan': 'Pro' })
        expect(logic.values.previewPerson).toMatchObject({
            properties: { first_name: 'Sam' },
            event: { properties: { plan: 'Pro' } },
        })

        logic.actions.pickPerson(GRACE)
        expect(logic.values.previewPerson).toEqual(GRACE)
        expect(logic.values.customProperties).toBeNull()
    })

    it('fills event values from the latest trigger event of the previewed person', async () => {
        jest.spyOn(api, 'query').mockResolvedValue({ results: [[JSON.stringify({ plan: 'Pro' })]] } as any)
        logic.actions.setTriggerEvent('upgraded')
        await expectLogic(logic).toDispatchActions(['loadPersonEventSuccess'])

        expect(renderEmailPreview('{{ event.properties.plan }}', logic.values.previewPerson)).toBe('Pro')
    })
})
