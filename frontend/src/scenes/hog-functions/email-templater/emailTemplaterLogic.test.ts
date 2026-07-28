import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    EditorRef,
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

describe('emailTemplaterLogic - design re-hydration', () => {
    let logic: ReturnType<typeof emailTemplaterLogic.build>
    let loadDesign: jest.Mock
    let onChange: jest.Mock
    let designUpdatedCallback: (() => void) | null

    const DESIGN_A = { body: { id: 'a', rows: [{ id: 'r1' }] } }
    const DESIGN_B = { body: { id: 'b', rows: [{ id: 'r2' }] } }

    const makeInlineProps = (design: Record<string, any>): EmailTemplaterLogicProps => ({
        value: { ...DEFAULT_EMAIL_TEMPLATE, design },
        onChange,
        type: 'native_email_template',
        layout: 'inline',
    })

    const fakeEditorRef = (exportedDesign: () => Record<string, any>): EditorRef =>
        ({
            editor: {
                loadDesign,
                addEventListener: (_event: string, callback: () => void) => {
                    designUpdatedCallback = callback
                },
                exportHtml: (callback: (data: any) => void) =>
                    callback({ html: '<p>edited</p>', design: exportedDesign() }),
                exportPlainText: (callback: (data: any) => void) => callback({ text: 'edited' }),
            },
        }) as unknown as EditorRef

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
        loadDesign = jest.fn()
        onChange = jest.fn()
        designUpdatedCallback = null
        logic = emailTemplaterLogic(makeInlineProps(DESIGN_A))
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('loads the design on ready, reloads on external change, and ignores its own export echo', async () => {
        let editorDesign: Record<string, any> = DESIGN_A
        logic.actions.setEmailEditorRef(fakeEditorRef(() => editorDesign))
        logic.actions.onEmailEditorReady()

        // Initial hydration from props.
        expect(loadDesign).toHaveBeenCalledTimes(1)
        expect(loadDesign).toHaveBeenLastCalledWith(DESIGN_A)

        // External change (e.g. an AI edit reloaded the parent) re-hydrates the open canvas.
        emailTemplaterLogic(makeInlineProps(DESIGN_B))
        expect(loadDesign).toHaveBeenCalledTimes(2)
        expect(loadDesign).toHaveBeenLastCalledWith(DESIGN_B)

        // A user edit in the canvas debounce-exports to the parent...
        editorDesign = { body: { id: 'c', rows: [{ id: 'r3' }] } }
        // Fake timers only around the debounce so mount-time loaders keep real timers.
        jest.useFakeTimers()
        designUpdatedCallback?.()
        await jest.advanceTimersByTimeAsync(500)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()
        expect(onChange).toHaveBeenCalledTimes(1)
        expect(onChange.mock.calls[0][0].design).toEqual(editorDesign)

        // ...and the parent echoing that value back must not redraw the canvas.
        emailTemplaterLogic(makeInlineProps(editorDesign))
        expect(loadDesign).toHaveBeenCalledTimes(2)
    })
})
