import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    EMAIL_TYPE_SUPPORTED_FIELDS,
    EditorRef,
    EmailTemplate,
    EmailTemplaterLogicProps,
    emailTemplaterLogic,
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

describe('emailTemplaterLogic', () => {
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
        jest.useRealTimers()
    })

    describe('advanced fields', () => {
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

    describe('modal content tab default', () => {
        it.each([
            {
                description: 'a blank email opens on the visual tab',
                value: { ...DEFAULT_EMAIL_TEMPLATE, html: '', text: '', design: null },
                expectedTab: 'visual',
            },
            {
                description: 'an email with html opens on the visual tab',
                value: DEFAULT_EMAIL_TEMPLATE,
                expectedTab: 'visual',
            },
            {
                description: 'a plain-text-only email opens on the plain text tab',
                value: { ...DEFAULT_EMAIL_TEMPLATE, html: '', design: null },
                expectedTab: 'plaintext',
            },
        ])('$description', async ({ value, expectedTab }) => {
            logic = emailTemplaterLogic(makeProps({ value }))
            logic.mount()

            logic.actions.setIsModalOpen(true)
            await expectLogic(logic).toMatchValues({ activeContentTab: expectedTab })
        })
    })

    describe('starting-point picker', () => {
        it('closes the picker when the editor modal closes', async () => {
            logic = emailTemplaterLogic(makeProps())
            logic.mount()

            logic.actions.setIsModalOpen(true)
            logic.actions.setIsTemplatePickerOpen(true)
            await expectLogic(logic).toMatchValues({ isTemplatePickerOpen: true })

            logic.actions.setIsModalOpen(false)
            await expectLogic(logic).toMatchValues({ isTemplatePickerOpen: false })
        })
    })

    describe('html-only emails', () => {
        it('loads a design wrapping the html so the canvas shows the email instead of starting blank', () => {
            const loadDesign = jest.fn()
            logic = emailTemplaterLogic(
                makeProps({ value: { ...DEFAULT_EMAIL_TEMPLATE, design: null, html: '<p>raw</p>' } })
            )
            logic.mount()
            logic.actions.setEmailEditorRef({
                editor: { loadDesign, addEventListener: jest.fn() },
            } as unknown as EditorRef)
            logic.actions.onEmailEditorReady()

            expect(loadDesign).toHaveBeenCalledTimes(1)
            const design = loadDesign.mock.calls[0][0]
            expect(design.body.rows[0].columns[0].contents[0]).toMatchObject({
                type: 'html',
                values: { html: '<p>raw</p>' },
            })
        })

        it('does not load anything when there is neither design nor html', () => {
            const loadDesign = jest.fn()
            logic = emailTemplaterLogic(makeProps({ value: { ...DEFAULT_EMAIL_TEMPLATE, design: null, html: '' } }))
            logic.mount()
            logic.actions.setEmailEditorRef({
                editor: { loadDesign, addEventListener: jest.fn() },
            } as unknown as EditorRef)
            logic.actions.onEmailEditorReady()

            expect(loadDesign).not.toHaveBeenCalled()
        })
    })

    describe('modal save', () => {
        let onChange: jest.Mock
        let editorListeners: Record<string, () => void>
        let editorDesign: Record<string, any>

        const DESIGN_NORMALIZED = { body: { id: 'normalized', rows: [{ id: 'r1' }] } }
        const DESIGN_EDITED = { body: { id: 'edited', rows: [{ id: 'r2' }] } }

        const fakeEditorRef = (): EditorRef =>
            ({
                editor: {
                    loadDesign: jest.fn(),
                    addEventListener: (event: string, callback: () => void) => {
                        editorListeners[event] = callback
                    },
                    exportHtml: (callback: (data: any) => void) =>
                        callback({ html: '<p>edited</p>', design: editorDesign }),
                    exportPlainText: (callback: (data: any) => void) => callback({ text: 'edited' }),
                },
            }) as unknown as EditorRef

        beforeEach(async () => {
            onChange = jest.fn()
            editorListeners = {}
            editorDesign = DESIGN_NORMALIZED
            logic = emailTemplaterLogic(
                makeProps({ value: { ...DEFAULT_EMAIL_TEMPLATE, design: null, html: '<p>raw</p>' }, onChange })
            )
            logic.mount()
            logic.actions.setEmailEditorRef(fakeEditorRef())
            logic.actions.onEmailEditorReady()
            // The load echo rebaselines to the editor's normalized export
            editorListeners['design:loaded']?.()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('a save without canvas edits keeps the stored html instead of the editor re-render', async () => {
            logic.actions.submitEmailTemplate()
            await expectLogic(logic).toFinishAllListeners()

            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange.mock.calls[0][0]).toMatchObject({ html: '<p>raw</p>' })
        })

        it('a save after a canvas edit persists the editor export', async () => {
            editorDesign = DESIGN_EDITED
            logic.actions.submitEmailTemplate()
            await expectLogic(logic).toFinishAllListeners()

            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange.mock.calls[0][0]).toMatchObject({
                html: '<p>edited</p>',
                text: 'edited',
                design: DESIGN_EDITED,
            })
        })
    })

    describe('inline layout live propagation', () => {
        let onChange: jest.Mock
        let loadDesign: jest.Mock
        let editorListeners: Record<string, () => void>
        let editorDesign: Record<string, any>

        const DESIGN_STORED = { body: { id: 'stored', rows: [{ id: 'r1' }] } }
        // What unlayer exports after normalizing DESIGN_STORED (it rewrites ids/defaults on load).
        const DESIGN_NORMALIZED = { body: { id: 'stored', rows: [{ id: 'r1' }], values: { normalized: true } } }
        const DESIGN_EDITED = { body: { id: 'edited', rows: [{ id: 'r2' }] } }

        const fakeEditorRef = (): EditorRef =>
            ({
                editor: {
                    loadDesign,
                    addEventListener: (event: string, callback: () => void) => {
                        editorListeners[event] = callback
                    },
                    exportHtml: (callback: (data: any) => void) =>
                        callback({ html: '<p>edited</p>', design: editorDesign }),
                    exportPlainText: (callback: (data: any) => void) => callback({ text: 'edited' }),
                },
            }) as unknown as EditorRef

        beforeEach(() => {
            onChange = jest.fn()
            loadDesign = jest.fn()
            editorListeners = {}
            editorDesign = DESIGN_NORMALIZED
            logic = emailTemplaterLogic(
                makeProps({
                    value: { ...DEFAULT_EMAIL_TEMPLATE, design: DESIGN_STORED },
                    onChange,
                    type: 'native_email_template',
                    layout: 'inline',
                })
            )
            logic.mount()
            logic.actions.setEmailEditorRef(fakeEditorRef())
            logic.actions.onEmailEditorReady()
        })

        it('propagates a user edit to the parent after the debounce', async () => {
            expect(loadDesign).toHaveBeenCalledWith(DESIGN_STORED)

            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']?.()
            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()

            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange.mock.calls[0][0]).toMatchObject({
                design: DESIGN_EDITED,
                html: '<p>edited</p>',
                text: 'edited',
            })
        })

        it('propagates an edit made immediately after a design load', async () => {
            // The load rebaselines via design:loaded...
            expect(editorListeners['design:loaded']).toBeTruthy()
            editorListeners['design:loaded']()
            await expectLogic(logic).toFinishAllListeners()

            // ...and an edit fired straight after must still reach the parent, not be
            // discarded as a load echo.
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']?.()
            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()

            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange.mock.calls[0][0]).toMatchObject({ design: DESIGN_EDITED })
        })

        it('rebaselines on design:loaded so the normalized export does not count as an edit', async () => {
            expect(editorListeners['design:loaded']).toBeTruthy()
            editorListeners['design:loaded']()
            await expectLogic(logic).toFinishAllListeners()

            jest.useFakeTimers()
            // The editor re-exports the normalized design unchanged - not a user edit.
            editorListeners['design:updated']?.()
            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()

            expect(onChange).not.toHaveBeenCalled()
        })
    })
})
