import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { AccountApi, CustomPropertyDefinitionApi } from '../../generated/api.schemas'
import { AccountPropertiesWidget } from './AccountPropertiesWidget'
import type { AccountWidgetPropertyReference } from './accountPropertiesWidgetConfig'
import { accountPropertyDataLogic } from './accountPropertyDataLogic'
import { accountSidebarConfigLogic } from './accountSidebarConfigLogic'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    userHasAccess: () => true,
}))

const PROJECT_ID = MOCK_DEFAULT_TEAM.id
const ACCOUNT_ID = '11111111-1111-4111-8111-111111111111'
const ACCOUNT_URL = '/api/projects/:project_id/accounts/:account_id/'
const DEFINITIONS_URL = '/api/projects/:project_id/custom_property_definitions/'
const EMPTY_PAGE = { count: 0, results: [] }
const nativeReferences: AccountWidgetPropertyReference[] = [{ kind: 'account', key: 'billing_id' }]
const mixedReferences: AccountWidgetPropertyReference[] = [
    ...nativeReferences,
    { kind: 'custom_property', id: '22222222-2222-4222-8222-222222222222' },
]
const account: AccountApi = {
    id: ACCOUNT_ID,
    name: 'Example account',
    notebooks: [],
    ignored_at: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    properties: { billing_id: 'billing-example' },
}

function createDeferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

function createWidget(references = nativeReferences): JSX.Element {
    return (
        <AccountPropertiesWidget
            projectId={PROJECT_ID}
            accountId={ACCOUNT_ID}
            instanceId="first"
            initialConfig={{ properties: references }}
        />
    )
}

function renderWidget(references = nativeReferences): ReturnType<typeof render> {
    return render(createWidget(references))
}

async function waitForNativeAccount(): Promise<void> {
    await waitFor(() =>
        expect(accountPropertyDataLogic({ projectId: PROJECT_ID, accountId: ACCOUNT_ID }).values.account).toEqual(
            account
        )
    )
}

async function finishRequests<T>(pending: { resolve: (value: T) => void }, value: T): Promise<void> {
    await act(async () => {
        pending.resolve(value)
        await expectLogic(accountSidebarConfigLogic({ projectId: PROJECT_ID })).toFinishAllListeners()
    })
}

describe('AccountPropertiesWidget source resolution', () => {
    beforeEach(() => {
        initKeaTests()
        silenceKeaLoadersErrors()
        useMocks({
            get: {
                [ACCOUNT_URL]: account,
                [DEFINITIONS_URL]: EMPTY_PAGE,
                '/api/projects/:project_id/account_relationship_definitions/': EMPTY_PAGE,
                '/api/projects/:project_id/user_customer_analytics_config/@me/': { pinned_properties: [] },
            },
        })
    })

    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
    })

    it.each([
        {
            selection: 'native-only',
            references: nativeReferences,
            source: 'definitions',
            state: 'pending',
            expected: 'ready',
        },
        {
            selection: 'native-only',
            references: nativeReferences,
            source: 'definitions',
            state: 'failed',
            expected: 'ready',
        },
        {
            selection: 'mixed',
            references: mixedReferences,
            source: 'definitions',
            state: 'pending',
            expected: 'loading',
        },
        { selection: 'mixed', references: mixedReferences, source: 'definitions', state: 'failed', expected: 'failed' },
        {
            selection: 'native-only',
            references: nativeReferences,
            source: 'account',
            state: 'pending',
            expected: 'loading',
        },
        {
            selection: 'native-only',
            references: nativeReferences,
            source: 'account',
            state: 'failed',
            expected: 'failed',
        },
    ] as const)(
        'shows $expected for a $selection widget when $source is $state',
        async ({ references, source, state, expected }) => {
            const pending = createDeferred<AccountApi | typeof EMPTY_PAGE>()
            useMocks({
                get: {
                    [source === 'account' ? ACCOUNT_URL : DEFINITIONS_URL]: () =>
                        state === 'pending' ? pending.promise : [500, { detail: 'Source unavailable' }],
                },
            })
            const { container } = renderWidget(references)
            try {
                const definitions = accountSidebarConfigLogic({ projectId: PROJECT_ID })
                const data = accountPropertyDataLogic({ projectId: PROJECT_ID, accountId: ACCOUNT_ID })
                await waitFor(() => {
                    const loading =
                        source === 'account'
                            ? data.values.accountLoading
                            : definitions.values.availableDefinitionsLoading
                    const failed =
                        source === 'account'
                            ? data.values.accountLoadFailed
                            : definitions.values.availableDefinitionsLoadFailed
                    expect(state === 'pending' ? loading : failed).toBe(true)
                })
                if (source === 'account') {
                    await waitFor(() => expect(definitions.values.availableDefinitions).not.toBeNull())
                } else {
                    await waitForNativeAccount()
                }
                if (expected === 'ready') {
                    expect(await screen.findByText('billing-example')).toBeVisible()
                } else if (expected === 'failed') {
                    expect(await screen.findByText('Could not load properties.')).toBeVisible()
                }
                expect(!!container.querySelector('[data-attr="account-properties-widget-loading"]')).toBe(
                    expected === 'loading'
                )
                expect(!!screen.queryByText('Could not load properties.')).toBe(expected === 'failed')
                expect(!!screen.queryByText('billing-example')).toBe(expected === 'ready')
                expect(
                    screen.queryByText('Could not refresh properties. These values may be out of date.')
                ).not.toBeInTheDocument()
            } finally {
                await finishRequests(pending, source === 'account' ? account : EMPTY_PAGE)
            }
        }
    )

    it('retries a native account failure without waiting for or refetching pending definitions', async () => {
        const pendingDefinitions = createDeferred<typeof EMPTY_PAGE>()
        const retriedAccount = createDeferred<AccountApi>()
        let failAccount = true
        const accountGet = jest.fn(() =>
            failAccount ? [500, { detail: 'Account unavailable' }] : retriedAccount.promise
        )
        const definitionsGet = jest.fn(() => pendingDefinitions.promise)
        useMocks({ get: { [ACCOUNT_URL]: accountGet, [DEFINITIONS_URL]: definitionsGet } })
        renderWidget()
        try {
            expect(await screen.findByText('Could not load properties.')).toBeVisible()
            await waitFor(() => expect(definitionsGet).toHaveBeenCalledTimes(1))
            const retryButton = screen.getAllByText('Try again')[0].closest('button')!
            expect(retryButton).not.toHaveAttribute('aria-disabled', 'true')
            failAccount = false
            act(() => {
                fireEvent.click(retryButton)
                fireEvent.click(retryButton)
            })
            await waitFor(() => expect(accountGet).toHaveBeenCalledTimes(2))
            await act(async () => {
                retriedAccount.resolve(account)
            })
            expect(await screen.findByText('billing-example')).toBeVisible()
            expect(accountGet).toHaveBeenCalledTimes(2)
            expect(definitionsGet).toHaveBeenCalledTimes(1)
            const definitions = accountSidebarConfigLogic({ projectId: PROJECT_ID })
            expect(definitions.values.availableDefinitions).toBeNull()
            expect(definitions.values.availableDefinitionsLoading).toBe(true)
        } finally {
            await act(async () => {
                retriedAccount.resolve(account)
                pendingDefinitions.resolve(EMPTY_PAGE)
                await expectLogic(accountSidebarConfigLogic({ projectId: PROJECT_ID })).toFinishAllListeners()
            })
        }
    })

    it('applies configuration changes without losing custom or native drafts or changing pins', async () => {
        const definition: CustomPropertyDefinitionApi = {
            id: '22222222-2222-4222-8222-222222222222',
            name: 'Plan',
            display_type: 'text',
            target_type: 'account',
            is_canonical: false,
            has_workflow_reference: false,
            source: null,
            references: [],
            created_at: '2026-01-01T00:00:00Z',
            created_by: 1,
            updated_at: null,
        }
        useMocks({
            get: {
                [DEFINITIONS_URL]: { count: 1, results: [definition] },
                '/api/projects/:project_id/accounts/:account_id/custom_property_values/': [
                    {
                        id: 'value-1',
                        account_id: ACCOUNT_ID,
                        definition_id: definition.id,
                        value: 'Starter',
                        created_at: '2026-01-01T00:00:00Z',
                        created_by_id: 1,
                    },
                ],
                '/api/projects/:project_id/accounts/:account_id/relationships/': [],
            },
        })
        const { rerender } = renderWidget([])
        const definitions = accountSidebarConfigLogic({ projectId: PROJECT_ID })
        await act(async () => {
            await expectLogic(definitions).toFinishAllListeners()
        })
        expect(
            screen.getByText("No properties selected. Use the tile's Edit action to choose properties.")
        ).toBeVisible()
        rerender(createWidget([{ kind: 'custom_property', id: definition.id }]))
        expect(await screen.findByText('Starter')).toBeVisible()
        fireEvent.click(screen.getByLabelText('Edit Plan'))
        fireEvent.change(screen.getByDisplayValue('Starter'), { target: { value: 'Unsaved plan' } })
        rerender(createWidget(mixedReferences))
        expect(await screen.findByText('billing-example')).toBeVisible()
        expect(screen.getByDisplayValue('Unsaved plan')).toBeVisible()
        fireEvent.click(screen.getByText('Cancel'))
        fireEvent.click(screen.getByLabelText('Edit Billing ID'))
        fireEvent.change(screen.getByDisplayValue('billing-example'), { target: { value: 'unsaved-billing' } })
        rerender(createWidget(nativeReferences))
        expect(screen.getByDisplayValue('unsaved-billing')).toBeVisible()
        expect(screen.queryByText('Starter')).not.toBeInTheDocument()
        expect(definitions.values.config?.pinned_properties).toEqual([])
    })

    it('does not show a definitions refresh warning for a native-only widget', async () => {
        renderWidget()
        const definitions = accountSidebarConfigLogic({ projectId: PROJECT_ID })
        await act(async () => {
            await expectLogic(definitions).toFinishAllListeners()
        })
        expect(await screen.findByText('billing-example')).toBeVisible()
        useMocks({ get: { [DEFINITIONS_URL]: () => [500, { detail: 'Definitions unavailable' }] } })
        await act(async () => {
            await expectLogic(definitions, () => definitions.actions.loadAvailableDefinitions()).toFinishAllListeners()
        })
        expect(screen.getByText('billing-example')).toBeVisible()
        expect(
            screen.queryByText('Could not refresh properties. These values may be out of date.')
        ).not.toBeInTheDocument()
    })
})
