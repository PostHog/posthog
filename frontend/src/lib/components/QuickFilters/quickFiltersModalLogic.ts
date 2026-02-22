import { LogicWrapper, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { QuickFilter } from '~/types'

import { QuickFiltersEvents } from './consts'
import { QuickFiltersLogicProps, quickFiltersLogic } from './quickFiltersLogic'
import type { quickFiltersModalLogicType } from './quickFiltersModalLogicType'

export const ModalView = {
    List: 'list',
    Form: 'form',
} as const

export type ModalView = (typeof ModalView)[keyof typeof ModalView]

export interface QuickFiltersModalLogicProps extends QuickFiltersLogicProps {
    /** Optional key to scope modal instances per consumer (e.g. per dashboard) */
    modalKey?: string | number
    /** Optional callback fired when a new quick filter is created while the modal is open */
    onNewFilterCreated?: (filter: QuickFilter) => void
}

export const quickFiltersModalLogic: LogicWrapper<quickFiltersModalLogicType> = kea<quickFiltersModalLogicType>([
    path(['lib', 'components', 'QuickFilters', 'quickFiltersModalLogic']),
    props({} as QuickFiltersModalLogicProps),
    key((props) => `${props.context}-${props.modalKey ?? 'default'}`),

    connect((props: QuickFiltersModalLogicProps) => ({
        actions: [quickFiltersLogic(props), ['deleteFilter']],
        values: [quickFiltersLogic(props), ['quickFilters']],
    })),

    actions({
        openModal: true,
        closeModal: true,
        setView: (view: ModalView) => ({ view }),
        setEditingFilter: (filter: QuickFilter | null) => ({ filter }),
        startAddNew: true,
        startEdit: (filter: QuickFilter) => ({ filter }),
        confirmDelete: (id: string) => ({ id }),
        handleFormBack: true,
        setSearchQuery: (query: string) => ({ query }),
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        view: [
            ModalView.List as ModalView,
            {
                setView: (_, { view }) => view,
                closeModal: () => ModalView.List,
                openModal: () => ModalView.List,
            },
        ],
        editedFilter: [
            null as QuickFilter | null,
            {
                setEditingFilter: (_, { filter }) => filter,
                closeModal: () => null,
                handleFormBack: () => null,
            },
        ],
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }) => query,
                closeModal: () => '',
                openModal: () => '',
            },
        ],
    }),

    selectors({
        modalTitle: [
            (s) => [s.view, s.editedFilter],
            (view: ModalView, editedFilter: QuickFilter | null): string => {
                if (view === ModalView.List) {
                    return 'Manage quick filters'
                }
                return editedFilter ? 'Edit quick filter' : 'Add quick filter'
            },
        ],
        filteredQuickFilters: [
            (s) => [s.quickFilters, s.searchQuery],
            (quickFilters: QuickFilter[], searchQuery: string): QuickFilter[] => {
                if (!searchQuery.trim()) {
                    return quickFilters
                }
                const query = searchQuery.toLowerCase()
                return quickFilters.filter(
                    (filter) =>
                        filter.name.toLowerCase().includes(query) ||
                        filter.property_name.toLowerCase().includes(query) ||
                        filter.options.some((opt) => opt.label?.toLowerCase().includes(query))
                )
            },
        ],
    }),

    listeners(({ actions, props, values, cache }) => ({
        startAddNew: () => {
            actions.setEditingFilter(null)
            actions.setView(ModalView.Form)
        },
        startEdit: ({ filter }) => {
            actions.setEditingFilter(filter)
            actions.setView(ModalView.Form)
        },
        confirmDelete: ({ id }) => {
            LemonDialog.open({
                title: 'Delete quick filter?',
                description: 'This action cannot be undone.',
                primaryButton: {
                    children: 'Delete',
                    status: 'danger',
                    onClick: () => actions.deleteFilter(id),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        handleFormBack: () => {
            actions.setView(ModalView.List)
        },
        openModal: () => {
            cache.filterIdsOnOpen = new Set(values.quickFilters.map((f) => f.id))
            posthog.capture(QuickFiltersEvents.QuickFiltersModalOpened, {
                context: props.context,
            })
        },
        setView: ({ view }) => {
            // When returning to list view, check if a new filter was added
            if (view === ModalView.List) {
                const previousIds: Set<string> = cache.filterIdsOnOpen ?? new Set()
                const newFilters = values.quickFilters.filter((f) => !previousIds.has(f.id))

                if (newFilters.length > 0 && props.onNewFilterCreated) {
                    const newFilter = newFilters[0]
                    props.onNewFilterCreated(newFilter)
                }

                cache.filterIdsOnOpen = new Set(values.quickFilters.map((f) => f.id))
            }
        },
    })),
])
