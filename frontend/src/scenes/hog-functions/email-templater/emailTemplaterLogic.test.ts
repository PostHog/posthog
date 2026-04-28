import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    emailTemplaterLogic,
    EMAIL_TYPE_SUPPORTED_FIELDS,
    EmailTemplate,
    EmailTemplaterLogicProps,
} from './emailTemplaterLogic'

const DEFAULT_EMAIL_TEMPLATE: EmailTemplate = {
    design: null,
    html: '<div>Hello</div>',
    subject: 'Welcome!',
    text: 'Hello',
    from: 'test@example.com',
    to: 'recipient@example.com',
}

function makeProps(overrides?: Partial<EmailTemplaterLogicProps>): EmailTemplaterLogicProps {
    return {
        value: DEFAULT_EMAIL_TEMPLATE,
        onChange: jest.fn(),
        type: 'native_email',
        ...overrides,
    }
}

const ADVANCED_FIELDS = EMAIL_TYPE_SUPPORTED_FIELDS.native_email.filter((f) => f.isAdvancedField)
const NON_ADVANCED_FIELDS = EMAIL_TYPE_SUPPORTED_FIELDS.native_email.filter((f) => !f.isAdvancedField)

describe('emailTemplaterLogic - advanced fields', () => {
    let logic: ReturnType<typeof emailTemplaterLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('hides advanced fields by default', async () => {
        logic = emailTemplaterLogic(makeProps())
        logic.mount()

        await expectLogic(logic).toMatchValues({
            visibleFields: NON_ADVANCED_FIELDS,
            hiddenAdvancedFields: ADVANCED_FIELDS,
        })
    })

    it('can reveal and then hide an advanced field', async () => {
        logic = emailTemplaterLogic(makeProps())
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.revealAdvancedField('replyTo')
        }).toMatchValues({
            revealedAdvancedFields: ['replyTo'],
            visibleFields: expect.arrayContaining([expect.objectContaining({ key: 'replyTo' })]),
            hiddenAdvancedFields: expect.arrayContaining([
                expect.objectContaining({ key: 'cc' }),
                expect.objectContaining({ key: 'bcc' }),
                expect.objectContaining({ key: 'preheader' }),
            ]),
        })

        // Revealing the same field again should not duplicate it
        logic.actions.revealAdvancedField('replyTo')
        expect(logic.values.revealedAdvancedFields).toEqual(['replyTo'])

        await expectLogic(logic, () => {
            logic.actions.hideAdvancedField('replyTo')
        }).toMatchValues({
            visibleFields: NON_ADVANCED_FIELDS,
            hiddenAdvancedFields: ADVANCED_FIELDS,
        })
    })

    it('auto-reveals advanced fields that have values on mount', async () => {
        logic = emailTemplaterLogic(
            makeProps({
                value: { ...DEFAULT_EMAIL_TEMPLATE, replyTo: 'reply@example.com' },
            })
        )
        logic.mount()

        await expectLogic(logic).toMatchValues({
            revealedAdvancedFields: ['replyTo'],
            visibleFields: expect.arrayContaining([expect.objectContaining({ key: 'replyTo' })]),
            hiddenAdvancedFields: expect.arrayContaining([
                expect.objectContaining({ key: 'cc' }),
                expect.objectContaining({ key: 'bcc' }),
                expect.objectContaining({ key: 'preheader' }),
            ]),
        })
    })

    it('auto-reveals advanced fields when props change with new values', async () => {
        const initialProps = makeProps()
        logic = emailTemplaterLogic(initialProps)
        logic.mount()

        await expectLogic(logic).toMatchValues({
            revealedAdvancedFields: [],
        })

        // Simulate parent updating props with a replyTo value
        const updatedProps = makeProps({
            value: { ...DEFAULT_EMAIL_TEMPLATE, replyTo: 'reply@example.com' },
        })
        emailTemplaterLogic(updatedProps)

        await expectLogic(logic).toMatchValues({
            revealedAdvancedFields: ['replyTo'],
            visibleFields: expect.arrayContaining([expect.objectContaining({ key: 'replyTo' })]),
        })
    })
})
