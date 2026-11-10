import {
    BuiltLogic,
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'

import {
    columnConfigurationsCreate,
    columnConfigurationsDestroy,
    columnConfigurationsList,
    columnConfigurationsPartialUpdate,
} from 'products/product_analytics/frontend/generated/api'
import type {
    ColumnConfigurationApi,
    PatchedColumnConfigurationApi,
} from 'products/product_analytics/frontend/generated/api.schemas'

import { AccountsEvents } from '../Accounts/constants'
import {
    DEFAULT_NOTES_ORDERING,
    EMPTY_NOTES_VIEW_STATE,
    accountNotesLogic,
    isAccountNotesListOrdering,
    type AccountNotesViewFilters,
    type AccountNotesViewState,
} from './accountNotesLogic'

export const ACCOUNT_NOTES_VIEWS_CONTEXT_KEY = 'customer_analytics_account_notes'

const DEFAULT_SOURCE_KEY = 'notes_tab'

// The column_configurations endpoint rejects an empty `columns` list. The Notes tables have fixed columns, so this records them.
export const ACCOUNT_NOTES_VIEW_COLUMNS = ['title', 'tags', 'created_by', 'created_at', 'last_modified_at']

export type NotesViewVisibility = 'private' | 'shared'

export interface AccountNotesViewsLogicProps {
    // The notes list the views apply to (the team-wide Notes tab when omitted); the views themselves are shared.
    sourceKey?: string
    sourceLogic?: BuiltLogic | LogicWrapper
}

type AccountNotesViewPayload = Pick<ColumnConfigurationApi, 'columns' | 'order_by'> & {
    filters: AccountNotesViewFilters
}

export function serializeAccountNotesView(state: AccountNotesViewState): AccountNotesViewPayload {
    return {
        columns: ACCOUNT_NOTES_VIEW_COLUMNS,
        order_by: [state.ordering],
        filters: {
            search: state.filters.search.trim(),
            tags: state.filters.tags,
            created_by: state.filters.created_by,
            assigned_to: state.filters.assigned_to,
            account_id: state.filters.account_id || null,
            account_name: state.filters.account_id ? state.filters.account_name : null,
        },
    }
}

function viewsScope(props: AccountNotesViewsLogicProps): 'notes_tab' | 'account' {
    return props.sourceLogic ? 'account' : 'notes_tab'
}

function stringList(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : []
}

function numberList(value: unknown): number[] {
    return Array.isArray(value) ? value.filter((entry): entry is number => typeof entry === 'number') : []
}

function optionalString(value: unknown): string | null {
    return typeof value === 'string' && value ? value : null
}

export function deserializeAccountNotesView(view: Partial<ColumnConfigurationApi>): AccountNotesViewState {
    // The backend represents empty filters as an array.
    const raw = (view.filters && !Array.isArray(view.filters) ? view.filters : {}) as Record<string, unknown>
    const ordering = view.order_by?.[0]
    const accountId = optionalString(raw.account_id)
    return {
        filters: {
            search: typeof raw.search === 'string' ? raw.search : '',
            tags: stringList(raw.tags),
            created_by: numberList(raw.created_by),
            assigned_to: numberList(raw.assigned_to),
            account_id: accountId,
            account_name: accountId ? optionalString(raw.account_name) : null,
        },
        ordering: isAccountNotesListOrdering(ordering) ? ordering : DEFAULT_NOTES_ORDERING,
    }
}

const ORDERING_LABELS: Record<string, string> = {
    created_at: 'Created, oldest first',
    '-created_at': 'Created, newest first',
    last_modified_at: 'Last modified, oldest first',
    '-last_modified_at': 'Last modified, newest first',
    title: 'Title, A to Z',
    '-title': 'Title, Z to A',
    created_by: 'Author, A to Z',
    '-created_by': 'Author, Z to A',
    account_name: 'Account, A to Z',
    '-account_name': 'Account, Z to A',
}

export interface AccountNotesViewSummary {
    /** What the view applies on the list it is shown on, one plain line per part. */
    applied: string[]
    /** Parts saved in the view that only apply on the team Notes tab. */
    teamTabOnly: string[]
}

/**
 * Spells out what a view saves, so "what goes into a view" is visible before saving and when picking one.
 * `memberName` turns a user id into a name; `scope` says which list the view is shown on.
 */
export function describeAccountNotesView(
    state: AccountNotesViewState,
    memberName: (userId: number) => string,
    scope: 'notes_tab' | 'account'
): AccountNotesViewSummary {
    const { filters } = state
    const applied: string[] = []
    const teamTabOnly: string[] = []
    if (filters.tags.length) {
        applied.push(`Tags: ${filters.tags.join(', ')}`)
    }
    if (filters.created_by.length) {
        applied.push(`Created by: ${filters.created_by.map(memberName).join(', ')}`)
    }
    if (filters.search.trim()) {
        applied.push(`Search: "${filters.search.trim()}"`)
    }
    const accountParts: string[] = []
    if (filters.account_id) {
        accountParts.push(`Account: ${filters.account_name ?? filters.account_id}`)
    }
    if (filters.assigned_to.length) {
        accountParts.push(`Assigned to: ${filters.assigned_to.map(memberName).join(', ')}`)
    }
    if (scope === 'account') {
        teamTabOnly.push(...accountParts)
    } else {
        applied.push(...accountParts)
    }
    const sortSummary = `Sort: ${ORDERING_LABELS[state.ordering] ?? state.ordering}`
    if (scope === 'account' && state.ordering.replace(/^-/, '') === 'account_name') {
        teamTabOnly.push(sortSummary)
        applied.push(`Sort: ${ORDERING_LABELS['-created_at']}`)
    } else {
        applied.push(sortSummary)
    }
    return { applied, teamTabOnly }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountNotesViewsLogicValues {
    currentViewId: string | null // source
    defaultViewState: AccountNotesViewState // source
    viewState: AccountNotesViewState // source
    currentTeamId: number | null // teamLogic
    canEditCurrentView: boolean
    currentView: ColumnConfigurationApi | null
    isCreating: boolean
    isDirty: boolean
    isViewFormSubmitting: boolean
    isViewFormValid: boolean
    showViewFormErrors: boolean
    viewForm: {
        name: string
        visibility: NotesViewVisibility
    }
    viewFormAllErrors: Record<string, any>
    viewFormChanged: boolean
    viewFormErrors: DeepPartialMap<
        {
            name: string
            visibility: NotesViewVisibility
        },
        ValidationErrorType
    >
    viewFormHasErrors: boolean
    viewFormManualErrors: Record<string, any>
    viewFormTouched: boolean
    viewFormTouches: Record<string, boolean>
    viewFormValidationErrors: DeepPartialMap<
        {
            name: string
            visibility: NotesViewVisibility
        },
        ValidationErrorType
    >
    viewToDelete: string | null
    viewToEdit: string | null
    views: ColumnConfigurationApi[]
    viewsLoadError: boolean
    viewsLoaded: boolean
    viewsLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountNotesViewsLogicActions {
    applyViewState: (
        viewState: AccountNotesViewState,
        currentViewId?: string | null | undefined
    ) => {
        currentViewId: string | null | undefined
        viewState: AccountNotesViewState
    } // source
    setCurrentViewId: (id: string | null) => {
        id: string | null
    } // source
    applyView: (view: ColumnConfigurationApi) => {
        view: ColumnConfigurationApi
    }
    clearView: () => {
        value: true
    }
    deleteView: ({ id }: { id: string }) => {
        id: string
    }
    deleteViewFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    deleteViewSuccess: (
        views: ColumnConfigurationApi[],
        payload?: {
            id: string
        }
    ) => {
        views: ColumnConfigurationApi[]
        payload?: {
            id: string
        }
    }
    loadViews: (_?: unknown) => unknown
    loadViewsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadViewsSuccess: (
        views: ColumnConfigurationApi[],
        payload?: unknown
    ) => {
        views: ColumnConfigurationApi[]
        payload?: unknown
    }
    resetViewForm: (values?: { name: string; visibility: NotesViewVisibility }) => {
        values?: {
            name: string
            visibility: NotesViewVisibility
        }
    }
    selectView: (id: string) => {
        id: string
    }
    setIsCreating: (isCreating: boolean) => {
        isCreating: boolean
    }
    setViewFormManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setViewFormValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setViewFormValues: (
        values: DeepPartial<{
            name: string
            visibility: NotesViewVisibility
        }>
    ) => {
        values: DeepPartial<{
            name: string
            visibility: NotesViewVisibility
        }>
    }
    setViewToDelete: (id: string | null) => {
        id: string | null
    }
    setViewToEdit: (id: string | null) => {
        id: string | null
    }
    submitViewForm: () => {
        value: boolean
    }
    submitViewFormFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitViewFormRequest: (viewForm: { name: string; visibility: NotesViewVisibility }) => {
        viewForm: {
            name: string
            visibility: NotesViewVisibility
        }
    }
    submitViewFormSuccess: (viewForm: { name: string; visibility: NotesViewVisibility }) => {
        viewForm: {
            name: string
            visibility: NotesViewVisibility
        }
    }
    touchViewFormField: (key: string) => {
        key: string
    }
    updateView: ({ id, updates }: { id: string; updates: PatchedColumnConfigurationApi }) => {
        id: string
        updates: PatchedColumnConfigurationApi
    }
    updateViewFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    updateViewSuccess: (
        views: ColumnConfigurationApi[],
        payload?: {
            id: string
            updates: PatchedColumnConfigurationApi
        }
    ) => {
        views: ColumnConfigurationApi[]
        payload?: {
            id: string
            updates: PatchedColumnConfigurationApi
        }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountNotesViewsLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        currentView: (views: ColumnConfigurationApi[], currentViewId: string | null) => ColumnConfigurationApi | null
        isDirty: (currentView: ColumnConfigurationApi | null, viewState: AccountNotesViewState) => boolean
        canEditCurrentView: (currentView: ColumnConfigurationApi | null) => boolean
    }
}

export type accountNotesViewsLogicType = MakeLogicType<
    accountNotesViewsLogicValues,
    accountNotesViewsLogicActions,
    AccountNotesViewsLogicProps,
    accountNotesViewsLogicMeta
>

export const accountNotesViewsLogic = kea<accountNotesViewsLogicType>([
    path((key) => [
        'products',
        'customer_analytics',
        'frontend',
        'components',
        'AccountNotes',
        'accountNotesViewsLogic',
        key,
    ]),
    props({} as AccountNotesViewsLogicProps),
    key((props) => props.sourceKey ?? DEFAULT_SOURCE_KEY),
    connect((props: AccountNotesViewsLogicProps) => {
        // The cast gives kea-typegen one concrete logic type to read; it crashes on the BuiltLogic | LogicWrapper union.
        const source = (props.sourceLogic ?? accountNotesLogic) as typeof accountNotesLogic
        return {
            values: [teamLogic, ['currentTeamId'], source, ['viewState', 'defaultViewState', 'currentViewId']],
            actions: [source, ['applyViewState', 'setCurrentViewId']],
        }
    }),
    actions({
        selectView: (id: string) => ({ id }),
        applyView: (view: ColumnConfigurationApi) => ({ view }),
        clearView: true,
        setIsCreating: (isCreating: boolean) => ({ isCreating }),
        setViewToDelete: (id: string | null) => ({ id }),
        setViewToEdit: (id: string | null) => ({ id }),
    }),
    loaders(({ values }) => ({
        views: [
            [] as ColumnConfigurationApi[],
            {
                loadViews: async (_: unknown = undefined, breakpoint): Promise<ColumnConfigurationApi[]> => {
                    const projectId = String(values.currentTeamId)
                    const views: ColumnConfigurationApi[] = []
                    while (true) {
                        const response = await columnConfigurationsList(projectId, {
                            context_key: ACCOUNT_NOTES_VIEWS_CONTEXT_KEY,
                            offset: views.length,
                        })
                        breakpoint()
                        views.push(...response.results)
                        if (!response.next || response.results.length === 0) {
                            break
                        }
                    }
                    return views
                },
                updateView: async ({
                    id,
                    updates,
                }: {
                    id: string
                    updates: PatchedColumnConfigurationApi
                }): Promise<ColumnConfigurationApi[]> => {
                    // An empty update means "overwrite the definition with the live filters".
                    const data =
                        Object.keys(updates).length === 0 ? serializeAccountNotesView(values.viewState) : updates
                    const response = await columnConfigurationsPartialUpdate(String(values.currentTeamId), id, data)
                    return values.views.map((view) => (view.id === id ? response : view))
                },
                deleteView: async ({ id }: { id: string }): Promise<ColumnConfigurationApi[]> => {
                    await columnConfigurationsDestroy(String(values.currentTeamId), id)
                    return values.views.filter((view) => view.id !== id)
                },
            },
        ],
    })),
    reducers({
        viewsLoaded: [false, { loadViewsSuccess: () => true }],
        viewsLoadError: [
            false,
            {
                loadViews: () => false,
                loadViewsSuccess: () => false,
                loadViewsFailure: () => true,
            },
        ],
        isCreating: [
            false,
            {
                setIsCreating: (_, { isCreating }) => isCreating,
                submitViewFormSuccess: () => false,
            },
        ],
        viewToDelete: [
            null as string | null,
            {
                setViewToDelete: (_, { id }) => id,
                deleteViewSuccess: () => null,
            },
        ],
        viewToEdit: [
            null as string | null,
            {
                setViewToEdit: (_, { id }) => id,
                updateViewSuccess: (state, { payload }) =>
                    payload?.id === state && Object.keys(payload.updates).length > 0 ? null : state,
            },
        ],
    }),
    selectors({
        currentView: [
            (s) => [s.views, s.currentViewId],
            (views: ColumnConfigurationApi[], currentViewId: string | null): ColumnConfigurationApi | null =>
                views.find((view) => view.id === currentViewId) ?? null,
        ],
        isDirty: [
            (s) => [s.currentView, s.viewState],
            (currentView: ColumnConfigurationApi | null, viewState: AccountNotesViewState): boolean =>
                currentView
                    ? !objectsEqual(
                          serializeAccountNotesView(deserializeAccountNotesView(currentView)),
                          serializeAccountNotesView(viewState)
                      )
                    : false,
        ],
        canEditCurrentView: [
            (s) => [s.currentView],
            (currentView: ColumnConfigurationApi | null): boolean => !!currentView,
        ],
    }),
    forms(({ actions, props, values }) => ({
        viewForm: {
            defaults: { name: '', visibility: 'private' as NotesViewVisibility },
            errors: ({ name }: { name: string }) => ({ name: !name?.trim() ? 'Name is required' : undefined }),
            submit: async ({ name, visibility }: { name: string; visibility: NotesViewVisibility }) => {
                if (values.viewToEdit) {
                    actions.updateView({ id: values.viewToEdit, updates: { name: name.trim(), visibility } })
                    return
                }
                const response = await columnConfigurationsCreate(String(values.currentTeamId), {
                    ...serializeAccountNotesView(values.viewState),
                    context_key: ACCOUNT_NOTES_VIEWS_CONTEXT_KEY,
                    name: name.trim(),
                    visibility,
                })
                actions.loadViewsSuccess([...values.views, response])
                actions.setCurrentViewId(response.id)
                actions.resetViewForm()
                posthog.capture(AccountsEvents.NotesTabViewSaved, { visibility, scope: viewsScope(props) })
            },
        },
    })),
    listeners(({ actions, props, values }) => ({
        selectView: ({ id }) => {
            const view = values.views.find((candidate) => candidate.id === id)
            if (view) {
                actions.applyView(view)
            }
        },
        applyView: ({ view }) => {
            actions.applyViewState(deserializeAccountNotesView(view), view.id)
            posthog.capture(AccountsEvents.NotesTabViewSelected, {
                visibility: view.visibility,
                scope: viewsScope(props),
            })
        },
        clearView: () => {
            // Each notes list resets to its own default sort, so clearing an account view stays newest first.
            actions.applyViewState(values.defaultViewState ?? EMPTY_NOTES_VIEW_STATE, null)
        },
        setViewToEdit: ({ id }) => {
            const view = id ? values.views.find((candidate) => candidate.id === id) : undefined
            if (view) {
                actions.setViewFormValues({ name: view.name ?? '', visibility: view.visibility ?? 'shared' })
            }
        },
        loadViewsSuccess: ({ views }) => {
            if (values.currentViewId && !views.some((view) => view.id === values.currentViewId)) {
                actions.setCurrentViewId(null)
            }
        },
        updateViewSuccess: ({ payload }) => {
            lemonToast.success('View updated')
            posthog.capture(AccountsEvents.NotesTabViewUpdated, { scope: viewsScope(props) })
            if (payload && Object.keys(payload.updates).length > 0) {
                actions.resetViewForm()
            }
        },
        updateViewFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to update view')
        },
        deleteViewSuccess: ({ payload }) => {
            if (payload?.id === values.currentViewId) {
                actions.clearView()
            }
            lemonToast.success('View deleted')
            posthog.capture(AccountsEvents.NotesTabViewDeleted, { scope: viewsScope(props) })
        },
        deleteViewFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to delete view')
        },
        loadViewsFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to load views')
        },
        submitViewFormFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to save view')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadViews()
    }),
])
