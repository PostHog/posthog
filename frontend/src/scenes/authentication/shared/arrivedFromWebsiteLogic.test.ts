import { setDocumentReferrer } from './authReferrer.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { arrivedFromWebsiteLogic, isWebsiteReferrer } from './arrivedFromWebsiteLogic'

describe('arrivedFromWebsiteLogic', () => {
    beforeEach(() => {
        initKeaTests()
        setDocumentReferrer('')
    })

    it.each([
        ['https://posthog.com/', true],
        ['https://posthog.com/pricing', true],
        ['https://www.posthog.com/docs/getting-started', true],
        ['', false],
        ['https://app.posthog.com/login', false],
        ['https://eu.posthog.com/signup', false],
        ['https://posthog.com.phishing.example/', false],
        ['https://example.com/?ref=https://posthog.com/', false],
        ['not-a-url', false],
    ])('reads %p as arrived-from-website %p', (referrer, expected) => {
        expect(isWebsiteReferrer(referrer)).toBe(expected)
    })

    it('answers from the referrer the document was opened with', async () => {
        setDocumentReferrer('https://posthog.com/pricing')
        const logic = arrivedFromWebsiteLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ arrivedFromWebsite: true })
    })
})
