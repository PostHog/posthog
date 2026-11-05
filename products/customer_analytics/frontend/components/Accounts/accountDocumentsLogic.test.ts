import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    accountsDocumentsCreate,
    accountsDocumentsLegalList,
    accountsDocumentsList,
    accountsDocumentsSyncCreate,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountDocumentApi,
    AccountLegalDocumentApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountDocumentsLogic, EMPTY_DOCUMENT_FORM } from './accountDocumentsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else: connected logics call other generated
    // functions on mount, and an absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsDocumentsList: jest.fn(),
    accountsDocumentsLegalList: jest.fn(),
    accountsDocumentsCreate: jest.fn(),
    accountsDocumentsSyncCreate: jest.fn(),
}))

const mockList = accountsDocumentsList as jest.MockedFunction<typeof accountsDocumentsList>
const mockLegalList = accountsDocumentsLegalList as jest.MockedFunction<typeof accountsDocumentsLegalList>
const mockCreate = accountsDocumentsCreate as jest.MockedFunction<typeof accountsDocumentsCreate>
const mockSync = accountsDocumentsSyncCreate as jest.MockedFunction<typeof accountsDocumentsSyncCreate>

const orderForm = {
    id: 'doc-1',
    title: 'Order form',
    source: 'pandadoc',
    document_type: 'order_form',
    status: 'sent',
    created_at: '2026-03-01T00:00:00Z',
} as AccountDocumentApi

const dpa = {
    id: 'legal-1',
    document_type: 'DPA',
    status: 'signed',
    created_at: '2026-04-01T00:00:00Z',
    download_available: true,
} as AccountLegalDocumentApi

describe('accountDocumentsLogic', () => {
    let logic: ReturnType<typeof accountDocumentsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
        jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mount = async (): Promise<void> => {
        logic = accountDocumentsLogic({ accountId: 'acc-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('merges registered and legal documents into one list, newest first', async () => {
        mockList.mockResolvedValue([orderForm])
        mockLegalList.mockResolvedValue([dpa])

        await mount()

        expect(logic.values.rows.map((row) => [row.kind, row.id])).toEqual([
            ['legal', 'legal-1'],
            ['account', 'doc-1'],
        ])
    })

    it('keeps legal documents when the registered documents fail to load', async () => {
        mockList.mockRejectedValue(new Error('network'))
        mockLegalList.mockResolvedValue([dpa])

        await mount()

        expect(logic.values.documentsResult).toEqual({ documents: null, loadFailed: true })
        expect(logic.values.rows.map((row) => row.id)).toEqual(['legal-1'])
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
    })

    it('adds a document from the editor and reloads the list', async () => {
        mockList.mockResolvedValueOnce([]).mockResolvedValueOnce([orderForm])
        mockLegalList.mockResolvedValue([])
        mockCreate.mockResolvedValue(orderForm)
        await mount()

        logic.actions.openEditor()
        logic.actions.setDocumentFormValues({ url: ' https://app.pandadoc.com/a/#/documents/abc123defg ' })
        logic.actions.submitDocumentForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockCreate).toHaveBeenCalledWith(
            expect.any(String),
            'acc-1',
            expect.objectContaining({ source: 'pandadoc', url: 'https://app.pandadoc.com/a/#/documents/abc123defg' })
        )
        expect(logic.values.editorOpen).toBe(false)
        expect(logic.values.rows.map((row) => row.id)).toEqual(['doc-1'])
    })

    it('does not submit a linked document without a title', async () => {
        mockList.mockResolvedValue([])
        mockLegalList.mockResolvedValue([])
        await mount()

        logic.actions.openEditor()
        logic.actions.setDocumentFormValues({
            ...EMPTY_DOCUMENT_FORM,
            source: 'link',
            url: 'https://docs.example.com/q.pdf',
        })
        logic.actions.submitDocumentForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockCreate).not.toHaveBeenCalled()
        expect(logic.values.documentFormErrors.title).toBe('Enter a title')
        expect(logic.values.editorOpen).toBe(true)
    })

    it('replaces a document in place after refreshing it from PandaDoc', async () => {
        mockList.mockResolvedValue([orderForm])
        mockLegalList.mockResolvedValue([])
        mockSync.mockResolvedValue({ ...orderForm, status: 'signed' })
        await mount()

        logic.actions.syncDocument(orderForm)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.syncingDocumentId).toBeNull()
        expect(logic.values.rows[0]).toMatchObject({ kind: 'account', document: { status: 'signed' } })
    })
})
