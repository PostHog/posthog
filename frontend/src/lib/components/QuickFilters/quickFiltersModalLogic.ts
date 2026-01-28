import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { QuickFilter } from '~/types'

import { QuickFiltersEvents } from './consts'
import { QuickFiltersLogicProps, quickFiltersLogic } from './quickFiltersLogic'
import type { quickFiltersModalLogicType } from './quickFiltersModalLogicType'

export type ModalView = 'list' | 'form'

export const quickFiltersModalLogic = kea<quickFiltersModalLogicType>([
    path(['lib', 'components', 'QuickFilters', 'quickFiltersModalLogic']),
    props({} as QuickFiltersLogicProps),
    key((props) => props.context),

    connect((props: QuickFiltersLogicProps) => ({
        actions: [quickFiltersLogic(props), ['deleteFilter']],
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
            'list' as ModalView,
            {
                setView: (_, { view }) => view,
                closeModal: () => 'list',
                openModal: () => 'list',
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
    }),

    selectors({
        modalTitle: [
            (s) => [s.view, s.editedFilter],
            (view: ModalView, editedFilter: QuickFilter | null): string => {
                if (view === 'list') {
                    return 'Manage quick filters'
                }
                return editedFilter ? 'Edit quick filter' : 'Add quick filter'
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        startAddNew: () => {
            actions.setEditingFilter(null)
            actions.setView('form')
        },
        startEdit: ({ filter }) => {
            actions.setEditingFilter(filter)
            actions.setView('form')
        },
        confirmDelete: ({ id }) => {
            if (confirm('Are you sure you want to delete this quick filter?')) {
                actions.deleteFilter(id)
            }
        },
        handleFormBack: () => {
            actions.setView('list')
        },
        openModal: () => {
            posthog.capture(QuickFiltersEvents.QuickFiltersModalOpened, {
                context: props.context,
            })
        },
    })),
])
