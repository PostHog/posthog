import { Editor as TiptapEditor } from '@tiptap/core'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Realm } from '~/types'

import { createEmailEditorAdapter } from 'products/workflows/frontend/EmailDocumentEditor/emailEditorAdapter'
import { buildEmailExtensions } from 'products/workflows/frontend/EmailDocumentEditor/emailExtensions'
import { NEW_TEMPLATE } from 'products/workflows/frontend/TemplateLibrary/constants'
import { MessageTemplate } from 'products/workflows/frontend/TemplateLibrary/types'

import {
    EMAIL_TYPE_SUPPORTED_FIELDS,
    EditorRef,
    EmailTemplate,
    EmailTemplaterLogicProps,
    buildHtmlWrapDesign,
    editorDesignForEmail,
    buildPersonPropertyMergeValue,
    emailTemplaterLogic,
    latestEmailEditSaved,
    saveWithLatestEmailEdit,
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

const renderAround = (block: string): string =>
    `<html><head><style>#u_body a { color: #00e; }</style></head><body class="clean-body u_body"><!--[if mso]><table><tr><td><![endif]--><table id="u_body"><tbody><tr><td><div class="u-row">${block}</div></td></tr></tbody></table></body></html>`
const RENDER_OF_OLD = renderAround('<p>old</p>')
const RENDER_WITH_FOOTER = renderAround('<p>old</p><p>P.S.</p>')
const RENDERED_PAGE = renderAround('<p>page</p>')
const RENDERED_PAGE_WITH_FOOTER = `<div>${RENDERED_PAGE}<p>footer</p></div>`
const RENDER_WITH_IMAGE = renderAround('<p>old</p><img src="https://example.com/offer.png">')
const UNLAYER_COLUMN_OPEN =
    '<!--[if (mso)|(IE)]><table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td align="center"><![endif]--><!--[if (!mso)&(!IE)]><!--><div style="height: 100%;"><!--<![endif]-->'
const UNLAYER_COLUMN_CLOSE =
    '<!--[if (!mso)&(!IE)]><!--></div><!--<![endif]--><!--[if (mso)|(IE)]></td></tr></table><![endif]-->'
const RENDER_IN_OUTLOOK_COLUMN = renderAround(`${UNLAYER_COLUMN_OPEN}<p>old</p>${UNLAYER_COLUMN_CLOSE}`)
const RENDER_WITH_OUTLOOK_FOOTER = renderAround('<p>old</p><!--[if mso]><p>footer</p><![endif]-->')
const RENDER_WITH_NON_OUTLOOK_FOOTER = renderAround('<p>old</p><!--[if !mso]><!--><p>footer</p><!--<![endif]-->')

jest.mock('products/workflows/frontend/EmailDocumentEditor/components/EmailHtmlBlockView', () => ({
    EmailHtmlBlockView: () => null,
}))
jest.mock('products/workflows/frontend/EmailDocumentEditor/components/EmailImageBlockView', () => ({
    EmailImageBlockView: () => null,
}))
jest.mock('products/workflows/frontend/EmailDocumentEditor/components/EmailVariableChip', () => ({
    EmailVariableChip: () => null,
}))

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
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})
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

    describe('email media library', () => {
        it.each([
            {
                description: 'identifies the project to Unlayer in the native editor',
                type: 'native_email',
                identified: true,
            },
            { description: 'leaves the destination editor untouched', type: 'email', identified: false },
        ] as const)('$description', ({ type, identified }) => {
            preflightLogic.mount()
            preflightLogic.actions.loadPreflightSuccess({ realm: Realm.Cloud } as any)

            logic = emailTemplaterLogic(makeProps({ type }))
            logic.mount()

            expect(logic.values.unlayerEditorUser?.id.startsWith('project-') ?? false).toBe(identified)
        })
    })

    describe('merge tags', () => {
        beforeEach(() => {
            useMocks({ get: { '/api/projects/:team_id/property_definitions/': { results: [{ name: 'email' }] } } })
        })

        it.each([
            { type: 'native_email_template', variables: undefined, expected: ['email'] },
            {
                type: 'native_email_transactional_template',
                variables: { variables: { first_name: '', reset_link: '' } },
                expected: ['variables.first_name', 'variables.reset_link'],
            },
        ] as const)('$type offers $expected', async ({ type, variables, expected }) => {
            logic = emailTemplaterLogic(makeProps({ type, variables }))
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const offered = Object.keys(logic.values.mergeTags).filter((key) => !key.startsWith('unsubscribe'))
            expect(offered).toEqual(expected)
        })

        it('pushes a newly added variable into the open editor', async () => {
            const setMergeTags = jest.fn()
            const props = makeProps({ type: 'native_email_transactional_template', variables: { variables: {} } })
            logic = emailTemplaterLogic(props)
            logic.mount()
            logic.actions.setEmailEditorRef({
                editor: { setMergeTags, addEventListener: jest.fn(), loadDesign: jest.fn() },
            } as any)
            logic.actions.onEmailEditorReady()

            emailTemplaterLogic({ ...props, variables: { variables: { code: '' } } })

            expect(setMergeTags).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    'variables.code': expect.objectContaining({ value: '{{ variables.code }}' }),
                })
            )
        })
    })

    describe('which editor opens', () => {
        const documentDesign = {
            ...buildHtmlWrapDesign('<p>doc</p>'),
            emailDocument: { version: 1, doc: { type: 'doc', attrs: { page: {} }, content: [] } },
        }
        const documentEmail = { ...DEFAULT_EMAIL_TEMPLATE, html: '<p>doc</p>', design: documentDesign as any }
        const blankEmail = { ...DEFAULT_EMAIL_TEMPLATE, html: '', text: '', design: null }

        it.each([
            { name: 'flag off: a blank email', flag: false, value: blankEmail, expected: false },
            { name: 'flag off: an email saved by the new editor', flag: false, value: documentEmail, expected: false },
            { name: 'flag on: a blank email', flag: true, value: blankEmail, expected: true },
            { name: 'flag on: an email saved by the new editor', flag: true, value: documentEmail, expected: true },
            {
                name: 'flag on: an old-editor email converts',
                flag: true,
                value: DEFAULT_EMAIL_TEMPLATE,
                expected: true,
            },
            {
                name: 'flag on: an html-only email converts',
                flag: true,
                value: { ...DEFAULT_EMAIL_TEMPLATE, html: '<p>Written elsewhere</p>', design: null },
                expected: true,
            },
            {
                name: 'flag on: a document that no longer matches the html converts from the html',
                flag: true,
                value: { ...documentEmail, html: '<p>changed elsewhere</p>' },
                expected: true,
            },
            {
                name: 'flag on: an email the new editor cannot rebuild converts as its own html',
                flag: true,
                value: {
                    ...DEFAULT_EMAIL_TEMPLATE,
                    html: '<p>Video</p>',
                    design: {
                        body: { rows: [{ cells: [1], columns: [{ contents: [{ type: 'video', values: {} }] }] }] },
                    },
                },
                expected: true,
            },
            {
                name: 'flag on: an email it cannot rebuild and has no html for stays on the old editor',
                flag: true,
                value: {
                    ...DEFAULT_EMAIL_TEMPLATE,
                    html: '',
                    design: {
                        body: { rows: [{ cells: [1], columns: [{ contents: [{ type: 'video', values: {} }] }] }] },
                    },
                },
                expected: false,
            },
        ])('$name', async ({ flag, value, expected }) => {
            featureFlagLogic.actions.setFeatureFlags(flag ? [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR] : [], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR]: flag,
            })
            logic = emailTemplaterLogic(makeProps({ value }))
            logic.mount()
            logic.actions.setIsModalOpen(true)

            await expectLogic(logic).toFinishAllListeners().toMatchValues({ usesDocumentEditor: expected })
        })

        it('converts an old-editor email only once its editor opens', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR]: true,
            })
            logic = emailTemplaterLogic(makeProps({ value: DEFAULT_EMAIL_TEMPLATE }))
            logic.mount()
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ emailConversion: null })

            logic.actions.setIsModalOpen(true)

            await expectLogic(logic).toFinishAllListeners().toMatchValues({ usesDocumentEditor: true })
        })

        it('keeps someone who chose the old editor there until they switch back', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR]: true,
            })
            logic = emailTemplaterLogic(makeProps({ value: DEFAULT_EMAIL_TEMPLATE }))
            logic.mount()
            logic.actions.setIsModalOpen(true)
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ usesDocumentEditor: true })

            logic.actions.setPrefersOldEmailEditor(true)
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ usesDocumentEditor: false })

            logic.actions.setPrefersOldEmailEditor(false)
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ usesDocumentEditor: true })
        })

        it.each([
            { name: 'keeps text that came with the html', text: 'Written by hand', expected: 'Written by hand' },
            {
                name: 'writes text over text that only repeats the html',
                text: ' Old ',
                expected: 'New (https://example.com)',
            },
            { name: 'writes text when the email has none', text: '', expected: 'New (https://example.com)' },
            {
                name: 'writes text over what the old editor wrote',
                text: 'From the old editor',
                design: { counters: { u_row: 1 }, body: buildHtmlWrapDesign('<p>Old</p>').body },
                expected: 'New (https://example.com)',
            },
            {
                name: 'writes text once the person asks for it',
                text: 'Written by hand',
                update: true,
                expected: 'New (https://example.com)',
            },
        ])('an edit $name', async ({ text, design, update, expected }) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR]: true,
            })
            const onChange = jest.fn()
            logic = emailTemplaterLogic({
                ...makeProps({ value: { ...blankEmail, html: '<p>Old</p>', text, design: (design ?? null) as any } }),
                layout: 'inline',
                onChange,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const editor = new TiptapEditor({
                extensions: buildEmailExtensions(''),
                content: logic.values.documentEditorInitialDoc,
            })
            logic.actions.setEmailEditorRef({ editor: createEmailEditorAdapter(editor) } as any)
            logic.actions.onEmailEditorReady()
            await expectLogic(logic).toFinishAllListeners()

            const html = '<a href="https://example.com">New</a>'
            editor.view.dispatch(editor.state.tr.setNodeAttribute(0, 'html', html))
            if (update) {
                editor.view.dispatch(editor.state.tr.setDocAttribute('ownPlainText', false))
            }
            await logic.asyncActions.flushPendingDesignEdit()

            expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ html, text: expected }))
            editor.destroy()
        })

        it('does not load the new template sample over the new editor starter', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR]: true,
            })
            const loadDesign = jest.fn()
            logic = emailTemplaterLogic(makeProps({ value: NEW_TEMPLATE.content.email as any }))
            logic.mount()
            logic.actions.setEmailEditorRef({
                editor: { loadDesign, addEventListener: jest.fn(), exportHtml: jest.fn() },
            } as any)
            logic.actions.onEmailEditorReady()
            await expectLogic(logic).toFinishAllListeners()

            expect(loadDesign).not.toHaveBeenCalled()
        })

        it.each([
            { when: 'after its conversion', settleFirst: true },
            { when: 'before its conversion finishes', settleFirst: false },
        ])('opens a new template on the starter when another email is left $when', async ({ settleFirst }) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR]: true,
            })
            const templateProps = { type: 'native_email_template', layout: 'inline' } as const
            const newTemplate = { ...templateProps, value: NEW_TEMPLATE.content.email as any }
            const fresh = emailTemplaterLogic(makeProps(newTemplate))
            fresh.mount()
            const starter = fresh.values.documentEditorInitialDoc
            fresh.unmount()

            logic = emailTemplaterLogic(
                makeProps({
                    ...templateProps,
                    emailKey: 'other',
                    value: { ...DEFAULT_EMAIL_TEMPLATE, preheader: 'Other preheader' },
                })
            )
            logic.mount()
            logic.actions.setActiveContentTab('plaintext')
            logic.actions.setTemplatingEngine('hog')
            if (settleFirst) {
                await expectLogic(logic).toFinishAllListeners()
            }

            emailTemplaterLogic(makeProps({ ...newTemplate, emailKey: 'new' }))

            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                documentEditorInitialDoc: starter,
                revealedAdvancedFields: [],
                activeContentTab: 'visual',
                templatingEngine: 'liquid',
            })
        })

        it('keeps the conversion and the tab when the same email changes', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR]: true,
            })
            const props = makeProps({ type: 'native_email_template', layout: 'inline', emailKey: 'same' })
            logic = emailTemplaterLogic(props)
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setActiveContentTab('plaintext')
            const converted = logic.values.convertedEmailDocument

            emailTemplaterLogic({ ...props, value: { ...DEFAULT_EMAIL_TEMPLATE, subject: 'New subject' } })

            expect(converted).not.toBeNull()
            expect(logic.values.convertedEmailDocument).toBe(converted)
            expect(logic.values.activeContentTab).toBe('plaintext')
        })

        it('keeps the destination email type on the old editor', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR]: true,
            })
            logic = emailTemplaterLogic(makeProps({ value: blankEmail, type: 'email' }))
            logic.mount()

            await expectLogic(logic).toMatchValues({ usesDocumentEditor: false })
        })

        it('refreshes the old-editor wrap of a document whose html changed elsewhere', () => {
            expect(editorDesignForEmail({ html: '<p>changed</p>', design: documentDesign as any })).toEqual(
                buildHtmlWrapDesign('<p>changed</p>')
            )
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

        it("applying a transactional template keeps the email's own sender and reply-to", async () => {
            logic = emailTemplaterLogic(
                makeProps({
                    value: { ...DEFAULT_EMAIL_TEMPLATE, from: { integrationId: 1 }, replyTo: 'team@example.com' },
                })
            )
            logic.mount()

            logic.actions.applyTemplate({
                id: 'template-1',
                name: 'Password reset',
                content: {
                    templating: 'liquid',
                    email: {
                        ...DEFAULT_EMAIL_TEMPLATE,
                        subject: 'Reset your password',
                        from: { integrationId: 2, name: 'PostHog Security' },
                        replyTo: 'security@example.com',
                    },
                },
            } as MessageTemplate)

            await expectLogic(logic).toMatchValues({
                emailTemplate: expect.objectContaining({
                    subject: 'Reset your password',
                    from: { integrationId: 1 },
                    replyTo: 'team@example.com',
                }),
            })
        })

        it('applying a text-only template clears the previous html body and design', async () => {
            const onChange = jest.fn()
            logic = emailTemplaterLogic(
                makeProps({
                    value: {
                        ...DEFAULT_EMAIL_TEMPLATE,
                        html: '<p>Hello from PostHog!</p>',
                        design: {} as EmailTemplate['design'],
                    },
                    onChange,
                })
            )
            logic.mount()

            logic.actions.applyTemplate({
                id: 'template-2',
                name: 'Plain receipt',
                content: {
                    templating: 'liquid',
                    email: { subject: 'Your receipt', text: 'Thanks for your order.' },
                },
            } as MessageTemplate)

            expect(onChange).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    subject: 'Your receipt',
                    text: 'Thanks for your order.',
                    html: '',
                    design: null,
                })
            )
        })

        it('applying a template whose stored wrap is stale loads its current html', () => {
            const loadDesign = jest.fn()
            logic = emailTemplaterLogic(makeProps())
            logic.mount()
            logic.actions.setEmailEditorRef({
                editor: { loadDesign, addEventListener: jest.fn() },
            } as unknown as EditorRef)
            logic.actions.onEmailEditorReady()
            loadDesign.mockClear()

            logic.actions.applyTemplate({
                id: 'template-3',
                name: 'Newsletter',
                content: {
                    templating: 'liquid',
                    email: { subject: 'News', html: '<p>new</p>', design: buildHtmlWrapDesign('<p>old</p>') },
                },
            } as MessageTemplate)

            expect(loadDesign).toHaveBeenCalledWith(buildHtmlWrapDesign('<p>new</p>'), '<p>new</p>', undefined)
        })
    })

    describe('custom sender', () => {
        it('clearing the custom sender sends one update without the name, address, or reply-to', () => {
            const onChange = jest.fn()
            logic = emailTemplaterLogic(
                makeProps({
                    value: {
                        ...DEFAULT_EMAIL_TEMPLATE,
                        from: { integrationId: 1, name: 'Support', email: 'support@example.com' },
                        replyTo: 'team@example.com',
                    },
                    onChange,
                    layout: 'inline',
                })
            )
            logic.mount()

            logic.actions.clearCustomSender()

            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange.mock.calls[0][0]).toMatchObject({
                from: { integrationId: 1, name: undefined, email: undefined },
                replyTo: '',
            })
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

        it.each([
            ['the html was rewritten', '<p>old</p>', '<p>new</p>', '<p>new</p>'],
            ['copy was appended to the block', '<p>old</p>', '<p>old</p><p>footer</p>', '<p>old</p><p>footer</p>'],
            ['copy was appended inside its Unlayer render', '<p>old</p>', RENDER_WITH_FOOTER, RENDER_WITH_FOOTER],
            [
                'the block itself is an Unlayer page that got a footer',
                RENDERED_PAGE,
                RENDERED_PAGE_WITH_FOOTER,
                RENDERED_PAGE_WITH_FOOTER,
            ],
            ['an image was added inside its Unlayer render', '<p>old</p>', RENDER_WITH_IMAGE, RENDER_WITH_IMAGE],
            [
                'an Outlook-only footer was added inside its Unlayer render',
                '<p>old</p>',
                RENDER_WITH_OUTLOOK_FOOTER,
                RENDER_WITH_OUTLOOK_FOOTER,
            ],
            [
                'a footer hidden from Outlook was added inside its Unlayer render',
                '<p>old</p>',
                RENDER_WITH_NON_OUTLOOK_FOOTER,
                RENDER_WITH_NON_OUTLOOK_FOOTER,
            ],
            ['the html is the Unlayer render of the wrap', '<p>old</p>', RENDER_OF_OLD, '<p>old</p>'],
            [
                'the html is the Unlayer render of the wrap in Outlook column wrappers',
                '<p>old</p>',
                RENDER_IN_OUTLOOK_COLUMN,
                '<p>old</p>',
            ],
        ])('when %s, the canvas loads a wrap of the right html', (_name, blockHtml, html, expectedBlockHtml) => {
            const loadDesign = jest.fn()
            logic = emailTemplaterLogic(
                makeProps({ value: { ...DEFAULT_EMAIL_TEMPLATE, design: buildHtmlWrapDesign(blockHtml), html } })
            )
            logic.mount()
            logic.actions.setEmailEditorRef({
                editor: { loadDesign, addEventListener: jest.fn() },
            } as unknown as EditorRef)
            logic.actions.onEmailEditorReady()

            expect(loadDesign).toHaveBeenCalledWith(buildHtmlWrapDesign(expectedBlockHtml))
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

        it.each([
            { trigger: 'a save', debounceMs: 0, start: () => logic.actions.flushPendingDesignEdit() },
            { trigger: 'the debounce', debounceMs: 500, start: () => {} },
        ])(
            'hands an edit still being read by $trigger to its own email when another one opens',
            async ({ debounceMs, start }) => {
                jest.useFakeTimers()
                let releaseExport = (): void => {}
                logic.actions.setEmailEditorRef({
                    editor: {
                        ...fakeEditorRef().editor,
                        exportHtml: (callback: (data: any) => void) => {
                            releaseExport = () => callback({ html: '<p>edited</p>', design: DESIGN_EDITED })
                        },
                    },
                } as unknown as EditorRef)
                editorListeners['design:updated']()
                start()
                await jest.advanceTimersByTimeAsync(debounceMs)

                const onNextChange = jest.fn()
                const nextEmail = { ...DEFAULT_EMAIL_TEMPLATE, subject: 'Next email' }
                emailTemplaterLogic({ ...logic.props, emailKey: 'next', value: nextEmail, onChange: onNextChange })
                releaseExport()
                await jest.advanceTimersByTimeAsync(1000)
                jest.useRealTimers()

                expect(onNextChange).not.toHaveBeenCalled()
                expect(onChange).toHaveBeenCalledTimes(1)
                expect(onChange).toHaveBeenCalledWith(
                    expect.objectContaining({ subject: DEFAULT_EMAIL_TEMPLATE.subject, design: DESIGN_EDITED })
                )
                expect(logic.values.emailTemplate).toEqual(nextEmail)
                expect(logic.values.latestEditUnsaved).toBe(false)
            }
        )

        it.each([
            { when: 'before another email opens', flushReadsFirst: true },
            { when: 'after another email opens', flushReadsFirst: false },
        ])(
            'hands an edit over once when two reads of it end and the newer one ends $when',
            async ({ flushReadsFirst }) => {
                jest.useFakeTimers()
                const heldExports: (() => void)[] = []
                logic.actions.setEmailEditorRef({
                    editor: {
                        ...fakeEditorRef().editor,
                        exportHtml: (callback: (data: any) => void) => {
                            heldExports.push(() => callback({ html: '<p>edited</p>', design: DESIGN_EDITED }))
                        },
                    },
                } as unknown as EditorRef)
                editorListeners['design:updated']()
                await jest.advanceTimersByTimeAsync(500)
                logic.actions.flushPendingDesignEdit()
                const [slowRead, flushRead] = heldExports
                const openNext = (): void => {
                    emailTemplaterLogic({ ...logic.props, emailKey: 'next', onChange: jest.fn() })
                }
                const order = flushReadsFirst ? [flushRead, openNext, slowRead] : [openNext, flushRead, slowRead]
                for (const step of order) {
                    step()
                    await jest.advanceTimersByTimeAsync(0)
                }
                jest.useRealTimers()

                expect(onChange).toHaveBeenCalledTimes(1)
                expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ design: DESIGN_EDITED }))
            }
        )

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

        it('hands over an edit not yet reported when the person saves straight away', async () => {
            editorListeners['design:loaded']()
            await expectLogic(logic).toFinishAllListeners()
            const save = jest.fn()

            editorDesign = DESIGN_EDITED
            await saveWithLatestEmailEdit(save)

            expect(save).toHaveBeenCalledTimes(1)
            expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ design: DESIGN_EDITED }))
        })

        it('saves again once the editor hands over an edit it failed to hand over before', async () => {
            editorListeners['design:loaded']()
            await expectLogic(logic).toFinishAllListeners()
            const save = jest.fn()
            const working = logic.values.emailEditorRef!.editor!.exportHtml
            ;(logic.values.emailEditorRef!.editor as any).exportHtml = () => {
                throw new Error('export failed')
            }
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()
            await saveWithLatestEmailEdit(save)
            expect(save).not.toHaveBeenCalled()

            ;(logic.values.emailEditorRef!.editor as any).exportHtml = working
            await saveWithLatestEmailEdit(save)

            expect(save).toHaveBeenCalledTimes(1)
            expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ design: DESIGN_EDITED }))
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

    describe('live changes in the modal layout', () => {
        let parent: { email: EmailTemplate }
        let loadDesign: jest.Mock
        let editorListeners: Record<string, () => void>
        let editorDesign: Record<string, any>
        let holdNextExport: boolean
        let releaseHeldExport: (() => void) | null

        const DESIGN_STORED = { body: { id: 'stored', rows: [{ id: 'r1' }] } }
        // What unlayer exports after normalizing DESIGN_STORED (it rewrites ids/defaults on load).
        const DESIGN_NORMALIZED = { body: { id: 'stored', rows: [{ id: 'r1' }], values: { normalized: true } } }
        const DESIGN_EDITED = { body: { id: 'edited', rows: [{ id: 'r2' }] } }
        const DESIGN_EXTERNAL = { body: { id: 'external', rows: [{ id: 'r3' }] } }
        const DESIGN_EDITED_AGAIN = { body: { id: 'edited-again', rows: [{ id: 'r4' }] } }

        const value = (overrides?: Partial<EmailTemplate>): EmailTemplate => ({
            ...DEFAULT_EMAIL_TEMPLATE,
            design: DESIGN_STORED,
            ...overrides,
        })

        const fakeEditorRef = (): EditorRef =>
            ({
                editor: {
                    loadDesign,
                    addEventListener: (event: string, callback: () => void) => {
                        editorListeners[event] = callback
                    },
                    exportHtml: (callback: (data: any) => void) => {
                        const exported = { html: '<p>edited</p>', design: editorDesign }
                        if (holdNextExport) {
                            holdNextExport = false
                            releaseHeldExport = () => callback(exported)
                            return
                        }
                        callback(exported)
                    },
                    exportPlainText: (callback: (data: any) => void) => callback({ text: 'edited' }),
                },
            }) as unknown as EditorRef

        const onChange = (email: EmailTemplate): void => {
            parent.email = email
        }

        const updateProps = (overrides?: Partial<EmailTemplate>): void => {
            // The logic is unkeyed: rebuilding with new props updates the mounted instance and
            // fires propsChanged, like a parent re-render would.
            emailTemplaterLogic(makeProps({ value: value(overrides), onChange, liveChanges: true }))
        }

        beforeEach(async () => {
            parent = { email: value() }
            loadDesign = jest.fn()
            editorListeners = {}
            editorDesign = DESIGN_NORMALIZED
            holdNextExport = false
            releaseHeldExport = null
            logic = emailTemplaterLogic(makeProps({ value: value(), onChange, liveChanges: true }))
            logic.mount()
            logic.actions.setIsModalOpen(true)
            logic.actions.setEmailEditorRef(fakeEditorRef())
            logic.actions.onEmailEditorReady()
            // The load echo rebaselines to the editor's normalized export.
            editorListeners['design:loaded']?.()
            await expectLogic(logic).toFinishAllListeners()
            expect(loadDesign).toHaveBeenCalledTimes(1)
        })

        it('propagates canvas edits while the modal is open', async () => {
            // Without liveChanges the modal layout never attaches this listener.
            expect(editorListeners['design:updated']).toBeTruthy()

            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()

            expect(parent.email).toMatchObject({ design: DESIGN_EDITED, text: 'edited' })
        })

        it('propagates meta field edits while the modal is open', async () => {
            logic.actions.setEmailTemplateValue('subject', 'Updated subject')

            expect(parent.email).toMatchObject({ subject: 'Updated subject' })
        })

        it('a plain-text edit replaces the html body, like the modal save does', async () => {
            logic.actions.setActiveContentTab('plaintext')
            logic.actions.setEmailTemplateValue('text', 'Plain words')

            expect(parent.email).toMatchObject({ text: 'Plain words', html: '' })
        })

        it('browser back mid-debounce flushes the pending canvas edit through the same path', async () => {
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            // Back button: the URL loses the param and urlToAction drives the close.
            router.actions.push(router.values.location.pathname, {})
            await jest.advanceTimersByTimeAsync(0)
            expect(parent.email).toMatchObject({ design: DESIGN_EDITED })
            expect(logic.values.isModalOpen).toBe(false)

            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()
            expect(parent.email).toMatchObject({ design: DESIGN_EDITED, text: 'edited' })
        })

        it('a flush picks up an edit the editor has not reported yet', async () => {
            editorDesign = DESIGN_EDITED
            await logic.asyncActions.flushPendingDesignEdit()

            expect(parent.email).toMatchObject({ design: DESIGN_EDITED })
        })

        it('switching the sender keeps a canvas edit made while the flush is exporting', async () => {
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            holdNextExport = true
            const flushed = logic.asyncActions.flushPendingDesignEdit()
            editorDesign = DESIGN_EDITED_AGAIN
            editorListeners['design:updated']()
            releaseHeldExport?.()
            await flushed

            expect(parent.email).toMatchObject({ design: DESIGN_EDITED_AGAIN })

            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('holds an edit it could not export, and a save waits for it instead of storing the older email', async () => {
            const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
            let exportFails = true
            logic.actions.setEmailEditorRef({
                editor: {
                    ...fakeEditorRef().editor,
                    exportPlainText: (callback: (data: any) => void) => {
                        if (exportFails) {
                            throw new Error('export failed')
                        }
                        callback({ text: 'edited' })
                    },
                },
            } as unknown as EditorRef)
            const save = jest.fn()
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            await jest.advanceTimersByTimeAsync(500)

            expect(parent.email.design).not.toEqual(DESIGN_EDITED)
            expect(toast).toHaveBeenCalledWith(expect.stringContaining("Couldn't save this email"), expect.anything())

            await saveWithLatestEmailEdit(save)
            expect(save).not.toHaveBeenCalled()

            exportFails = false
            await saveWithLatestEmailEdit(save)
            jest.useRealTimers()

            expect(save).toHaveBeenCalledTimes(1)
            expect(parent.email).toMatchObject({ design: DESIGN_EDITED, text: 'edited' })
            toast.mockRestore()
        })

        it('saves once when the person clicks save again while the editor is still being read', async () => {
            const save = jest.fn()
            editorDesign = DESIGN_EDITED
            holdNextExport = true

            const first = saveWithLatestEmailEdit(save)
            const second = saveWithLatestEmailEdit(save)
            releaseHeldExport?.()
            await Promise.all([first, second])

            expect(save).toHaveBeenCalledTimes(1)
        })

        it('lets a save through when the editor closes while it is being read', async () => {
            editorDesign = DESIGN_EDITED
            holdNextExport = true

            const saved = latestEmailEditSaved()
            logic.unmount()
            releaseHeldExport?.()

            await expect(saved).resolves.toBe(true)
            expect(parent.email).toMatchObject({ design: DESIGN_EDITED })
        })

        it.each([
            {
                how: 'another email opens',
                leave: (): void => {
                    emailTemplaterLogic({ ...logic.props, emailKey: 'next' })
                },
            },
            {
                how: 'two more emails open',
                leave: (): void => {
                    emailTemplaterLogic({ ...logic.props, emailKey: 'next' })
                    emailTemplaterLogic({ ...logic.props, emailKey: 'third' })
                },
            },
            { how: 'the editor closes', leave: (): void => logic.unmount() },
        ])('blocks the save of an email whose edit could not be read when $how', async ({ leave }) => {
            const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
            logic.actions.setEmailEditorRef({
                editor: { ...fakeEditorRef().editor, exportPlainText: () => {} },
            } as unknown as EditorRef)
            const save = jest.fn()
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            const saved = saveWithLatestEmailEdit(save)
            leave()
            await jest.advanceTimersByTimeAsync(5000)
            await saved

            expect(save).not.toHaveBeenCalled()
            expect(toast).toHaveBeenCalledWith(expect.stringContaining("Couldn't save this email"), expect.anything())

            await saveWithLatestEmailEdit(save)
            jest.useRealTimers()
            expect(save).toHaveBeenCalledTimes(1)
            toast.mockRestore()
        })

        it('lets a save through once the editor that held a failed edit is gone', async () => {
            const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
            logic.actions.setEmailEditorRef({
                editor: {
                    ...fakeEditorRef().editor,
                    exportPlainText: () => {
                        throw new Error('export failed')
                    },
                },
            } as unknown as EditorRef)
            const save = jest.fn()
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            await jest.advanceTimersByTimeAsync(500)
            await saveWithLatestEmailEdit(save)
            expect(save).not.toHaveBeenCalled()

            logic.actions.setEmailEditorRef(null)
            await saveWithLatestEmailEdit(save)
            jest.useRealTimers()

            expect(save).toHaveBeenCalledTimes(1)
            toast.mockRestore()
        })

        it('lets a save through when a load echo with no change cannot be read as text', async () => {
            const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
            logic.actions.setEmailEditorRef({
                editor: {
                    ...fakeEditorRef().editor,
                    exportPlainText: () => {
                        throw new Error('export failed')
                    },
                },
            } as unknown as EditorRef)
            const save = jest.fn()
            jest.useFakeTimers()
            editorListeners['design:updated']()
            await jest.advanceTimersByTimeAsync(500)
            await saveWithLatestEmailEdit(save)
            jest.useRealTimers()

            expect(save).toHaveBeenCalledTimes(1)
            expect(toast).not.toHaveBeenCalled()
            toast.mockRestore()
        })

        it('lets a save through when the canvas cannot be read but nothing was edited', async () => {
            const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
            logic.actions.setEmailEditorRef({
                editor: {
                    ...fakeEditorRef().editor,
                    exportPlainText: () => {
                        throw new Error('export failed')
                    },
                },
            } as unknown as EditorRef)
            const save = jest.fn()
            await saveWithLatestEmailEdit(save)

            expect(save).toHaveBeenCalledTimes(1)
            expect(toast).not.toHaveBeenCalled()
            toast.mockRestore()
        })

        it('lets a save through when the canvas stops answering and nothing was edited', async () => {
            logic.actions.setEmailEditorRef({
                editor: { ...fakeEditorRef().editor, exportPlainText: () => {} },
            } as unknown as EditorRef)
            const save = jest.fn()
            jest.useFakeTimers()
            const saved = saveWithLatestEmailEdit(save)
            await jest.advanceTimersByTimeAsync(5000)
            await saved
            jest.useRealTimers()

            expect(save).toHaveBeenCalledTimes(1)
        })

        it('a flush on the plain-text tab picks up an edit the old editor has not reported yet', async () => {
            logic.actions.setActiveContentTab('plaintext')
            editorDesign = DESIGN_EDITED
            await logic.asyncActions.flushPendingDesignEdit()

            expect(parent.email).toMatchObject({ design: DESIGN_EDITED })
        })

        it('saves a canvas edit still waiting when the plain-text tab opens', async () => {
            const save = jest.fn()
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            logic.actions.setActiveContentTab('plaintext')
            await saveWithLatestEmailEdit(save)
            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()

            expect(save).toHaveBeenCalledTimes(1)
            expect(parent.email).toMatchObject({ design: DESIGN_EDITED })
        })

        it('leaves the email alone on a save when no design was ever loaded into the canvas', async () => {
            logic.unmount()
            parent = { email: value({ design: null, html: '', text: 'Plain text only' }) }
            logic = emailTemplaterLogic(makeProps({ value: parent.email, onChange, liveChanges: true }))
            logic.mount()
            logic.actions.setIsModalOpen(true)
            logic.actions.setEmailEditorRef({
                editor: { ...fakeEditorRef().editor, registerProvider: () => {}, registerCallback: () => {} },
            } as unknown as EditorRef)
            logic.actions.onEmailEditorReady()
            await expectLogic(logic).toFinishAllListeners()
            const before = parent.email
            editorDesign = DESIGN_EDITED
            await logic.asyncActions.flushPendingDesignEdit()

            expect(parent.email).toBe(before)
        })

        it('leaves the email alone on a save while a newly mounted editor is still loading', async () => {
            const before = parent.email
            logic.actions.setEmailEditorRef(fakeEditorRef())
            editorDesign = DESIGN_EDITED
            await logic.asyncActions.flushPendingDesignEdit()

            expect(parent.email).toBe(before)
        })

        it('still picks up an unreported edit after a re-render hands over the same editor again', async () => {
            const ref = logic.values.emailEditorRef
            logic.actions.setEmailEditorRef(null)
            logic.actions.setEmailEditorRef(ref)
            editorDesign = DESIGN_EDITED
            await logic.asyncActions.flushPendingDesignEdit()

            expect(parent.email).toMatchObject({ design: DESIGN_EDITED })
        })

        it('reads the canvas early again once the editor confirms its loaded design', async () => {
            updateProps({ design: DESIGN_EDITED_AGAIN })
            editorDesign = DESIGN_EDITED
            const before = parent.email
            await logic.asyncActions.flushPendingDesignEdit()
            expect(parent.email).toBe(before)

            editorDesign = DESIGN_NORMALIZED
            editorListeners['design:loaded']?.()
            await expectLogic(logic).toFinishAllListeners()
            editorDesign = DESIGN_EDITED
            await logic.asyncActions.flushPendingDesignEdit()
            expect(parent.email).toMatchObject({ design: DESIGN_EDITED })
        })

        it('blocks the save when an edit is waiting and the canvas stops answering', async () => {
            const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
            logic.actions.setEmailEditorRef({
                editor: { ...fakeEditorRef().editor, exportPlainText: () => {} },
            } as unknown as EditorRef)
            const save = jest.fn()
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            const saved = saveWithLatestEmailEdit(save)
            await jest.advanceTimersByTimeAsync(5000)
            await saved
            jest.useRealTimers()

            expect(save).not.toHaveBeenCalled()
            expect(toast).toHaveBeenCalledWith(expect.stringContaining("Couldn't save this email"), expect.anything())
            toast.mockRestore()
        })

        it('keeps the editor open and says so when an edit fails to save on close', async () => {
            const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
            logic.actions.setEmailEditorRef({
                editor: {
                    ...fakeEditorRef().editor,
                    exportPlainText: () => {
                        throw new Error('export failed')
                    },
                },
            } as unknown as EditorRef)
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            logic.actions.closeWithConfirmation()
            await jest.advanceTimersByTimeAsync(0)
            jest.useRealTimers()

            expect(logic.values.isModalOpen).toBe(true)
            expect(toast).toHaveBeenCalledWith(expect.stringContaining("Couldn't save this email"), expect.anything())
            toast.mockRestore()
        })

        it.each([
            {
                trigger: 'closing and reopening the editor',
                leave: (): void => logic.actions.closeWithConfirmation(),
                reopen: true,
            },
            {
                trigger: 'switching the sender',
                leave: (): void => void logic.asyncActions.flushPendingDesignEdit(),
                reopen: false,
            },
        ])('$trigger mid-debounce keeps the pending canvas edit', async ({ leave, reopen }) => {
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            leave()
            await jest.advanceTimersByTimeAsync(0)
            expect(parent.email).toMatchObject({ design: DESIGN_EDITED, text: 'edited' })

            if (reopen) {
                logic.actions.setIsModalOpen(true)
            }
            logic.actions.setEmailEditorRef({
                editor: {
                    loadDesign,
                    addEventListener: () => {},
                    registerProvider: () => {},
                    registerCallback: () => {},
                    exportHtml: (callback: (data: any) => void) =>
                        callback({ html: '', design: { body: { id: 'blank', rows: [] } } }),
                    exportPlainText: (callback: (data: any) => void) => callback({ text: '' }),
                },
            } as unknown as EditorRef)
            logic.actions.onEmailEditorReady()
            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()

            expect(parent.email).toMatchObject({ design: DESIGN_EDITED, text: 'edited' })
        })

        it('loads an externally changed design into the mounted canvas', async () => {
            updateProps({ design: DESIGN_EXTERNAL })
            await expectLogic(logic).toFinishAllListeners()

            expect(loadDesign).toHaveBeenCalledTimes(2)
            expect(loadDesign).toHaveBeenLastCalledWith(DESIGN_EXTERNAL)
        })

        it.each([
            ['as exported', DESIGN_EDITED],
            [
                'after a save drops undefined keys',
                { body: { ...DESIGN_EDITED.body, values: { fontFamily: undefined } } },
            ],
        ])('does not reload the canvas when our own edit echoes back through the parent %s', async (_, exported) => {
            jest.useFakeTimers()
            editorDesign = exported
            editorListeners['design:updated']()
            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()
            expect(parent.email.design).toEqual(exported)

            updateProps({ design: JSON.parse(JSON.stringify(parent.email.design)) })
            await expectLogic(logic).toFinishAllListeners()

            expect(loadDesign).toHaveBeenCalledTimes(1)
        })

        it('does not clobber a canvas edit whose debounce has not flushed with an external design', async () => {
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()

            // The external design lands inside the 500ms debounce window.
            updateProps({ design: DESIGN_EXTERNAL })
            expect(loadDesign).toHaveBeenCalledTimes(1)

            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()

            // The user's in-flight edit still propagates and wins.
            expect(parent.email).toMatchObject({ design: DESIGN_EDITED })
        })

        it('does not reload the same external design when an unrelated field changes', async () => {
            updateProps({ design: DESIGN_EXTERNAL })
            await expectLogic(logic).toFinishAllListeners()
            expect(loadDesign).toHaveBeenCalledTimes(2)

            updateProps({ design: DESIGN_EXTERNAL, subject: 'Changed elsewhere' })
            await expectLogic(logic).toFinishAllListeners()

            expect(loadDesign).toHaveBeenCalledTimes(2)
        })

        it('reloads an external design we once pushed if it returns after a local edit', async () => {
            updateProps({ design: DESIGN_EXTERNAL })
            await expectLogic(logic).toFinishAllListeners()
            expect(loadDesign).toHaveBeenCalledTimes(2)

            // The user edits the canvas away from the external design...
            jest.useFakeTimers()
            editorDesign = DESIGN_EDITED
            editorListeners['design:updated']()
            await jest.advanceTimersByTimeAsync(500)
            jest.useRealTimers()
            await expectLogic(logic).toFinishAllListeners()
            // ...and the parent echoes that edit back into props...
            updateProps({ design: DESIGN_EDITED })
            await expectLogic(logic).toFinishAllListeners()

            // ...so a later revert to that design elsewhere must load again, not be skipped
            // as already applied.
            updateProps({ design: DESIGN_EXTERNAL })
            await expectLogic(logic).toFinishAllListeners()

            expect(loadDesign).toHaveBeenCalledTimes(3)
            expect(loadDesign).toHaveBeenLastCalledWith(DESIGN_EXTERNAL)
        })
    })

    describe('editor URL sync', () => {
        it('opening pushes ?editor=email and closing strips it', async () => {
            logic = emailTemplaterLogic(makeProps())
            logic.mount()

            logic.actions.setIsModalOpen(true)
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.searchParams.editor).toBe('email')

            logic.actions.setIsModalOpen(false)
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.searchParams.editor).toBeUndefined()
        })

        it('removing the param from the url (browser back) closes the editor', async () => {
            logic = emailTemplaterLogic(makeProps())
            logic.mount()
            logic.actions.setIsModalOpen(true)
            await expectLogic(logic).toFinishAllListeners()

            router.actions.push(router.values.location.pathname, {})
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.isModalOpen).toBe(false)
        })

        it('a url already carrying the param opens the editor on mount', async () => {
            router.actions.push('/some-page', { editor: 'email' })

            logic = emailTemplaterLogic(makeProps())
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.isModalOpen).toBe(true)
        })

        it('unmounting while open strips the param, so the next editor does not auto-open', async () => {
            logic = emailTemplaterLogic(makeProps())
            logic.mount()
            logic.actions.setIsModalOpen(true)
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.searchParams.editor).toBe('email')

            // Switching nodes or closing the step panel unmounts the templater without closing it.
            logic.unmount()
            expect(router.values.searchParams.editor).toBeUndefined()

            logic = emailTemplaterLogic(makeProps())
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.isModalOpen).toBe(false)
        })

        it('the inline layout neither writes nor reads the param', async () => {
            router.actions.push('/some-page', { editor: 'email' })

            logic = emailTemplaterLogic(makeProps({ layout: 'inline' }))
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.isModalOpen).toBe(false)

            logic.actions.setIsModalOpen(true)
            router.actions.push('/some-page', {})
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.isModalOpen).toBe(true)
        })
    })
})

describe('buildPersonPropertyMergeValue', () => {
    // Never emit double quotes: they end an HTML attribute like a link href, and entity-encoded they
    // render an empty value. A bare identifier uses dot access; everything else uses single-quoted
    // brackets.
    it.each([
        ['first_name', '{{person.properties.first_name}}'],
        ['$browser', "{{person.properties['$browser']}}"],
        ['renews on', "{{person.properties['renews on']}}"],
        ['a.b', "{{person.properties['a.b']}}"],
        ["it's", "{{person.properties['it\\'s']}}"],
    ])('builds %s as %s', (name, expected) => {
        expect(buildPersonPropertyMergeValue(name)).toBe(expected)
    })
})
