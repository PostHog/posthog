import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { AccountsEvents } from '../../components/Accounts/constants'
import {
    accountViewsCreate,
    accountViewsDestroy,
    accountViewsList,
    accountViewsPartialUpdate,
    accountViewsRetrieve,
    userCustomerAnalyticsConfigPartialUpdate,
    userCustomerAnalyticsConfigRetrieve,
} from '../../generated/api'
import type {
    AccountDetailTabsConfigApi,
    AccountViewApi,
    UserCustomerAnalyticsConfigApi,
} from '../../generated/api.schemas'
import { createAccountViewContent, type AccountViewComponentInstance } from './accountViewDocument'
import { accountViewsLogic } from './accountViewsLogic'

jest.mock('../../generated/api', () => ({
    ...jest.requireActual('../../generated/api'),
    accountViewsCreate: jest.fn(),
    accountViewsDestroy: jest.fn(),
    accountViewsList: jest.fn(),
    accountViewsPartialUpdate: jest.fn(),
    accountViewsRetrieve: jest.fn(),
    userCustomerAnalyticsConfigPartialUpdate: jest.fn(),
    userCustomerAnalyticsConfigRetrieve: jest.fn(),
}))

const components: AccountViewComponentInstance[] = [
    {
        nodeId: 'example-private-note',
        kind: 'notes',
        span: 6,
        title: 'Invented private tile title',
        config: { searchTerm: 'invented-private-search' },
    },
    {
        nodeId: 'example-private-usage',
        kind: 'usage',
        span: 6,
        config: { dateRange: { date_from: '-14d', date_to: null } },
    },
]
const view: AccountViewApi = {
    id: '11111111-2222-4333-8444-555555555555',
    name: 'Invented private view name',
    visibility: 'private',
    content: createAccountViewContent(components),
    text_content: 'Invented private view content',
    version: 1,
    created_by: 1,
    last_modified_by: 1,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    can_edit: true,
    can_delete: true,
    can_change_visibility: true,
}

const tabSettings: AccountDetailTabsConfigApi = {
    ordered_tab_ids: ['system:notes', `view:${view.id}`],
    hidden_tab_ids: ['system:usage'],
    default_tab_id: `view:${view.id}`,
}
const userConfig: UserCustomerAnalyticsConfigApi = {
    pinned_properties: [],
    task_digest: { enabled: false, send_time: '09:00', cadence: 'weekdays' },
    account_detail_tabs: { ordered_tab_ids: [], hidden_tab_ids: [], default_tab_id: null },
}

type WriteOperation = 'create' | 'save' | 'rename' | 'remove' | 'delete' | 'tabs'
const operations: WriteOperation[] = ['create', 'save', 'rename', 'remove', 'delete', 'tabs']
const successEvents = {
    create: AccountsEvents.AccountViewSaved,
    save: AccountsEvents.AccountViewSaved,
    rename: AccountsEvents.AccountViewTileRenamed,
    remove: AccountsEvents.AccountViewTileRemoved,
    delete: AccountsEvents.AccountViewDeleted,
    tabs: AccountsEvents.AccountViewTabSettingsSaved,
}
const failureEvents = {
    create: AccountsEvents.AccountViewSaveFailed,
    save: AccountsEvents.AccountViewSaveFailed,
    rename: AccountsEvents.AccountViewTileRenameFailed,
    remove: AccountsEvents.AccountViewTileRemovalFailed,
    delete: AccountsEvents.AccountViewDeletionFailed,
    tabs: AccountsEvents.AccountViewTabSettingsSaveFailed,
}

function createDeferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

function createWriteResponse(operation: WriteOperation): AccountViewApi {
    return {
        ...view,
        id: operation === 'create' ? '66666666-7777-4888-8999-000000000000' : view.id,
        version: 2,
        content: createAccountViewContent(operation === 'remove' ? components.slice(1) : components),
    }
}

describe('accountViewsLogic tracking', () => {
    let logic: ReturnType<typeof accountViewsLogic.build>
    let capture: jest.SpiedFunction<typeof posthog.capture>
    const mockCreate = jest.mocked(accountViewsCreate)
    const mockUpdate = jest.mocked(accountViewsPartialUpdate)
    const mockDelete = jest.mocked(accountViewsDestroy)
    const mockConfigUpdate = jest.mocked(userCustomerAnalyticsConfigPartialUpdate)

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests(false)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]: true })
        jest.mocked(accountViewsList).mockResolvedValue([view])
        jest.mocked(accountViewsRetrieve).mockResolvedValue({ ...view, version: 2 })
        jest.mocked(userCustomerAnalyticsConfigRetrieve).mockResolvedValue(userConfig)
        mockCreate.mockReset().mockResolvedValue(view)
        mockUpdate.mockReset().mockResolvedValue(view)
        mockDelete.mockReset().mockResolvedValue(undefined)
        mockConfigUpdate.mockReset().mockResolvedValue(userConfig)
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'example-error-toast')
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        logic = accountViewsLogic({ projectId: 1 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        featureFlagLogic.unmount()
        jest.restoreAllMocks()
    })

    function getAccountViewCaptures(): Parameters<typeof posthog.capture>[] {
        return capture.mock.calls.filter(([event]) => event.startsWith('customer analytics account view '))
    }

    function startWrite(operation: WriteOperation): void {
        if (operation === 'create') {
            logic.actions.openCreateEditor()
            logic.actions.setEditorName('Invented private input name')
            logic.actions.addEditorComponent('notes')
            logic.actions.addEditorComponent('usage')
            logic.actions.saveEditor()
        } else if (operation === 'save') {
            logic.actions.openEditEditor(view)
            logic.actions.setEditorName('Invented private input name')
            logic.actions.saveEditor()
        } else if (operation === 'rename') {
            logic.actions.openTileEditor(view.id, components[0].nodeId, 'Invented private input title')
            logic.actions.saveTileEditor()
        } else if (operation === 'remove') {
            logic.actions.removeViewComponent(view.id, components[0].nodeId)
        } else if (operation === 'delete') {
            logic.actions.deleteView(view.id, view.version)
        } else {
            logic.actions.openConfigure(tabSettings)
            logic.actions.saveConfig()
        }
    }

    it.each(operations)(
        'reports %s only after acknowledgement with exactly the allowed properties',
        async (operation) => {
            const response = createDeferred<void>()
            const started = createDeferred<void>()
            const acknowledgedView = createWriteResponse(operation)
            const write = async (): Promise<void> => {
                started.resolve(undefined)
                await response.promise
            }
            const writeView = async (): Promise<AccountViewApi> => {
                await write()
                return acknowledgedView
            }
            mockCreate.mockImplementation(writeView)
            mockUpdate.mockImplementation(writeView)
            mockDelete.mockImplementation(write)
            mockConfigUpdate.mockImplementation(async () => {
                await write()
                return { ...userConfig, account_detail_tabs: tabSettings }
            })

            startWrite(operation)
            await started.promise
            expect(capture.mock.calls.map(([event]) => event)).not.toContain(successEvents[operation])
            response.resolve(undefined)
            await expectLogic(logic).toFinishAllListeners()

            const expectedEntries = {
                create: [[AccountsEvents.AccountViewEditorOpened, { is_new: true }]],
                save: [[AccountsEvents.AccountViewEditorOpened, { is_new: false }]],
                rename: [[AccountsEvents.AccountViewTileEditorOpened]],
                remove: [[AccountsEvents.AccountViewTileRemovalStarted]],
                delete: [[AccountsEvents.AccountViewDeletionStarted]],
                tabs: [
                    [AccountsEvents.AccountViewTabSettingsOpened],
                    [AccountsEvents.AccountViewTabSettingsSaveStarted],
                ],
            }[operation]
            const expectedProperties =
                operation === 'create' || operation === 'save'
                    ? { is_new: operation === 'create', component_count: 2 }
                    : operation === 'rename' || operation === 'remove'
                      ? { component_count: operation === 'remove' ? 1 : 2 }
                      : operation === 'tabs'
                        ? { has_default: true, ordered_count: 2, hidden_count: 1 }
                        : undefined
            const expectedOutcome = expectedProperties
                ? [successEvents[operation], expectedProperties]
                : [successEvents[operation]]
            expect(getAccountViewCaptures()).toEqual([...expectedEntries, expectedOutcome])
            if (operation === 'delete') {
                expect(logic.values.views.find(({ id }) => id === view.id)).toBeUndefined()
            } else if (operation === 'tabs') {
                expect(logic.values.config?.account_detail_tabs).toEqual(tabSettings)
                expect(logic.values.configureOpen).toBe(false)
            } else {
                expect(logic.values.views.find(({ id }) => id === acknowledgedView.id)?.version).toBe(2)
            }
        }
    )

    it.each(operations.flatMap((operation) => [409, 500].map((status) => ({ operation, status }))))(
        'reports failed $operation ($status) without success or private error content',
        async ({ operation, status }) => {
            const error = new ApiError('Invented private error message', status, undefined, {
                detail: 'Invented private error response',
            })
            mockCreate.mockRejectedValueOnce(error)
            mockUpdate.mockRejectedValueOnce(error)
            mockDelete.mockRejectedValueOnce(error)
            mockConfigUpdate.mockRejectedValueOnce(error)
            startWrite(operation)
            await expectLogic(logic).toFinishAllListeners()

            const expectedProperties = {
                ...(operation === 'create' || operation === 'save' ? { is_new: operation === 'create' } : {}),
                failure_type: status === 409 && operation !== 'tabs' ? 'conflict' : 'request',
            }
            expect(capture.mock.calls.filter(([event]) => event === failureEvents[operation])).toEqual([
                [failureEvents[operation], expectedProperties],
            ])
            expect(capture.mock.calls.map(([event]) => event)).not.toContain(successEvents[operation])
            expect(JSON.stringify(capture.mock.calls)).not.toMatch(
                /Invented|11111111|example-private|invented-private|-14d/
            )
            if (operation === 'create' || operation === 'save') {
                expect(logic.values.editorOpen).toBe(true)
                expect(logic.values.editorConflict).toBe(status === 409)
            } else if (operation === 'delete') {
                expect(logic.values.views).toContainEqual(view)
                expect(logic.values.editorConflict).toBe(status === 409)
            } else if (operation === 'tabs') {
                expect(logic.values.configureOpen).toBe(true)
                expect(logic.values.configSaving).toBe(false)
                expect(logic.values.editorConflict).toBe(false)
            }
        }
    )

    it.each(['editor', 'tabs'])(
        'does not report another %s entry or save for reloads or generic success actions',
        async (surface) => {
            if (surface === 'editor') {
                logic.actions.openEditEditor(view)
                logic.actions.reloadEditor()
                await expectLogic(logic).toFinishAllListeners()
                logic.actions.saveEditorSuccess(view)
                logic.actions.updateViewComponentConfig(view.id, components[0].nodeId, {
                    searchTerm: 'Invented private new config',
                })
            } else {
                logic.actions.openConfigure(tabSettings)
                logic.actions.openConfigure(tabSettings)
                logic.actions.loadConfigSuccess(userConfig)
                logic.actions.saveConfigSuccess(userConfig)
            }
            await expectLogic(logic).toFinishAllListeners()
            const expectedEntry =
                surface === 'editor'
                    ? [AccountsEvents.AccountViewEditorOpened, { is_new: false }]
                    : [AccountsEvents.AccountViewTabSettingsOpened]
            expect(getAccountViewCaptures()).toEqual([expectedEntry])
            if (surface === 'editor') {
                logic.actions.setEditorOpen(false)
                logic.actions.openEditEditor(view)
            } else {
                logic.actions.setConfigureOpen(false)
                logic.actions.openConfigure(tabSettings)
            }
            expect(getAccountViewCaptures()).toEqual([expectedEntry, expectedEntry])
        }
    )

    it.each(['editor', 'tabs'])('reports a blocked %s save without a write or success', async (surface) => {
        if (surface === 'editor') {
            logic.actions.openCreateEditor()
            logic.actions.saveEditor()
        } else {
            logic.actions.openConfigure(tabSettings)
            logic.actions.loadConfigFailure(new ApiError('Invented private load error', 500))
            logic.actions.saveConfig()
        }
        await expectLogic(logic).toFinishAllListeners()
        expect(mockCreate).not.toHaveBeenCalled()
        expect(mockConfigUpdate).not.toHaveBeenCalled()
        expect(getAccountViewCaptures()).toEqual(
            surface === 'editor'
                ? [
                      [AccountsEvents.AccountViewEditorOpened, { is_new: true }],
                      [AccountsEvents.AccountViewSaveFailed, { is_new: true, failure_type: 'validation' }],
                  ]
                : [
                      [AccountsEvents.AccountViewTabSettingsOpened],
                      [AccountsEvents.AccountViewTabSettingsSaveFailed, { failure_type: 'unavailable' }],
                  ]
        )
    })
})
