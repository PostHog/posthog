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
import {
    createAccountViewContent,
    parseAccountViewContent,
    type AccountViewComponentInstance,
} from './accountViewDocument'
import { accountViewsLogic, type accountViewsLogicValues } from './accountViewsLogic'

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
const updatedView: AccountViewApi = { ...view, version: 2 }
const createdView: AccountViewApi = { ...updatedView, id: '66666666-7777-4888-8999-000000000000' }
const removedTileView: AccountViewApi = { ...updatedView, content: createAccountViewContent(components.slice(1)) }
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
const updatedUserConfig: UserCustomerAnalyticsConfigApi = { ...userConfig, account_detail_tabs: tabSettings }

type Capture = Parameters<typeof posthog.capture>
type WriteFailure = { status: number; failureType: 'conflict' | 'request' }
interface WriteScenario {
    operation: 'create' | 'save' | 'rename' | 'remove' | 'delete' | 'tabs'
    start: () => void
    mockWrite: (write: () => Promise<void>) => void
    entries: Capture[]
    success: Capture
    successValues: Partial<accountViewsLogicValues>
    failureValues: Partial<accountViewsLogicValues>
    showsEditorConflict: boolean
    failureEvent: string
    failureContext?: { is_new: boolean }
    failures: WriteFailure[]
}
const conflictFailures: WriteFailure[] = [
    { status: 409, failureType: 'conflict' },
    { status: 500, failureType: 'request' },
]

function createDeferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe('accountViewsLogic tracking', () => {
    let logic: ReturnType<typeof accountViewsLogic.build>
    let capture: jest.SpiedFunction<typeof posthog.capture>
    const mockCreate = jest.mocked(accountViewsCreate)
    const mockUpdate = jest.mocked(accountViewsPartialUpdate)
    const mockDelete = jest.mocked(accountViewsDestroy)
    const mockConfigUpdate = jest.mocked(userCustomerAnalyticsConfigPartialUpdate)
    const scenarios: WriteScenario[] = [
        {
            operation: 'create',
            start: () => {
                logic.actions.openCreateEditor()
                logic.actions.setEditorName('Invented private input name')
                logic.actions.addEditorComponent('notes')
                logic.actions.addEditorComponent('usage')
                logic.actions.saveEditor()
            },
            mockWrite: (write) => mockCreate.mockImplementationOnce(() => write().then(() => createdView)),
            entries: [[AccountsEvents.AccountViewEditorOpened, { is_new: true }]],
            success: [AccountsEvents.AccountViewSaved, { is_new: true, component_count: 2 }],
            successValues: { views: [view, createdView] },
            failureValues: { editorOpen: true },
            showsEditorConflict: true,
            failureEvent: AccountsEvents.AccountViewSaveFailed,
            failureContext: { is_new: true },
            failures: conflictFailures,
        },
        {
            operation: 'save',
            start: () => {
                logic.actions.openEditEditor(view)
                logic.actions.setEditorName('Invented private input name')
                logic.actions.saveEditor()
            },
            mockWrite: (write) => mockUpdate.mockImplementationOnce(() => write().then(() => updatedView)),
            entries: [[AccountsEvents.AccountViewEditorOpened, { is_new: false }]],
            success: [AccountsEvents.AccountViewSaved, { is_new: false, component_count: 2 }],
            successValues: { views: [updatedView] },
            failureValues: { editorOpen: true },
            showsEditorConflict: true,
            failureEvent: AccountsEvents.AccountViewSaveFailed,
            failureContext: { is_new: false },
            failures: conflictFailures,
        },
        {
            operation: 'rename',
            start: () => {
                logic.actions.openTileEditor(view.id, components[0].nodeId, 'Invented private input title')
                logic.actions.saveTileEditor()
            },
            mockWrite: (write) => mockUpdate.mockImplementationOnce(() => write().then(() => updatedView)),
            entries: [[AccountsEvents.AccountViewTileEditorOpened]],
            success: [AccountsEvents.AccountViewTileRenamed, { component_count: 2 }],
            successValues: { views: [updatedView] },
            failureValues: {},
            showsEditorConflict: false,
            failureEvent: AccountsEvents.AccountViewTileRenameFailed,
            failures: conflictFailures,
        },
        {
            operation: 'remove',
            start: () => logic.actions.removeViewComponent(view.id, components[0].nodeId),
            mockWrite: (write) => mockUpdate.mockImplementationOnce(() => write().then(() => removedTileView)),
            entries: [[AccountsEvents.AccountViewTileRemovalStarted]],
            success: [AccountsEvents.AccountViewTileRemoved, { component_count: 1 }],
            successValues: { views: [removedTileView] },
            failureValues: {},
            showsEditorConflict: false,
            failureEvent: AccountsEvents.AccountViewTileRemovalFailed,
            failures: conflictFailures,
        },
        {
            operation: 'delete',
            start: () => logic.actions.deleteView(view.id, view.version),
            mockWrite: (write) => mockDelete.mockImplementationOnce(write),
            entries: [[AccountsEvents.AccountViewDeletionStarted]],
            success: [AccountsEvents.AccountViewDeleted],
            successValues: { views: [] },
            failureValues: { views: [view] },
            showsEditorConflict: true,
            failureEvent: AccountsEvents.AccountViewDeletionFailed,
            failures: conflictFailures,
        },
        {
            operation: 'tabs',
            start: () => {
                logic.actions.openConfigure(tabSettings)
                logic.actions.saveConfig()
            },
            mockWrite: (write) => mockConfigUpdate.mockImplementationOnce(() => write().then(() => updatedUserConfig)),
            entries: [
                [AccountsEvents.AccountViewTabSettingsOpened],
                [AccountsEvents.AccountViewTabSettingsSaveStarted],
            ],
            success: [
                AccountsEvents.AccountViewTabSettingsSaved,
                { has_default: true, ordered_count: 2, hidden_count: 1 },
            ],
            successValues: { config: updatedUserConfig, configureOpen: false },
            failureValues: { configureOpen: true, configSaving: false },
            showsEditorConflict: false,
            failureEvent: AccountsEvents.AccountViewTabSettingsSaveFailed,
            failures: [
                { status: 409, failureType: 'request' },
                { status: 500, failureType: 'request' },
            ],
        },
    ]

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests(false)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]: true })
        jest.mocked(accountViewsList).mockResolvedValue([view])
        jest.mocked(accountViewsRetrieve).mockResolvedValue(updatedView)
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

    function getAccountViewCaptures(): Capture[] {
        return capture.mock.calls.filter(([event]) => event.startsWith('customer analytics account view '))
    }

    it.each(scenarios)(
        'reports $operation only after acknowledgement with exactly the allowed properties',
        async (scenario) => {
            const response = createDeferred<void>()
            const started = createDeferred<void>()
            scenario.mockWrite(async () => {
                started.resolve(undefined)
                await response.promise
            })
            scenario.start()
            await started.promise
            expect(getAccountViewCaptures()).toEqual(scenario.entries)
            response.resolve(undefined)
            await expectLogic(logic).toFinishAllListeners()
            expect(getAccountViewCaptures()).toEqual([...scenario.entries, scenario.success])
            expect(logic.values).toMatchObject(scenario.successValues)
        }
    )

    it.each(scenarios.flatMap((scenario) => scenario.failures.map((failure) => ({ ...scenario, ...failure }))))(
        'reports failed $operation ($status) without success or private error content',
        async (scenario) => {
            scenario.mockWrite(async () => {
                throw new ApiError('Invented private error message', scenario.status, undefined, {
                    detail: 'Invented private error response',
                })
            })
            scenario.start()
            await expectLogic(logic).toFinishAllListeners()
            expect(getAccountViewCaptures()).toEqual([
                ...scenario.entries,
                [scenario.failureEvent, { ...scenario.failureContext, failure_type: scenario.failureType }],
            ])
            expect(JSON.stringify(capture.mock.calls)).not.toMatch(
                /Invented|11111111|example-private|invented-private|-14d/
            )
            expect(logic.values).toMatchObject({
                ...scenario.failureValues,
                editorConflict: scenario.showsEditorConflict && scenario.failureType === 'conflict',
            })
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

    it('retains a failed properties tile config and saves it without changing other tiles or pins', async () => {
        const firstConfig = { properties: [{ kind: 'account', key: 'website_domain' }] }
        const secondConfig = {
            properties: [
                { kind: 'account', key: 'known_emails' },
                { kind: 'relationship', id: '22222222-2222-4222-8222-222222222222' },
            ],
        }
        let propertiesView: AccountViewApi = {
            ...view,
            content: createAccountViewContent([
                { nodeId: 'first', kind: 'properties', span: 6, config: firstConfig },
                { nodeId: 'second', kind: 'properties', span: 6, config: secondConfig },
                ...components,
            ]),
        }
        jest.mocked(accountViewsList).mockResolvedValue([propertiesView])
        mockUpdate.mockImplementation(async (_, __, patch) => {
            propertiesView = { ...propertiesView, content: patch.content ?? propertiesView.content, version: 2 }
            return propertiesView
        })
        await expectLogic(logic, () => logic.actions.loadViews()).toFinishAllListeners()
        const changed = { properties: [...secondConfig.properties].reverse() }
        logic.actions.openTileEditor(view.id, 'first', 'Properties', {
            propertiesConfig: firstConfig,
            accountId: 'account-one',
        })
        logic.actions.setTileEditorPropertiesConfig(changed)
        mockUpdate.mockRejectedValueOnce(new ApiError('Save failed', 500))
        await expectLogic(logic, () => {
            logic.actions.saveTileEditor()
            logic.actions.saveTileEditor()
        }).toFinishAllListeners()
        expect(mockUpdate).toHaveBeenCalledTimes(1)
        expect(logic.values.tileEditor?.propertiesConfig).toEqual(changed)
        await expectLogic(logic, () => logic.actions.saveTileEditor()).toFinishAllListeners()
        expect(logic.values.tileEditor).toBeNull()
        expect(parseAccountViewContent(logic.values.views[0].content).map(({ config }) => config)).toEqual([
            changed,
            secondConfig,
            ...components.map(({ config }) => config),
        ])
        expect(logic.values.config?.pinned_properties).toEqual([])
    })

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
