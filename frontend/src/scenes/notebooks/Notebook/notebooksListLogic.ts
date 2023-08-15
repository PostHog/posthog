import { actions, BuiltLogic, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { loaders } from 'kea-loaders'
import { NotebookListItemType, NotebookNodeType, NotebookTarget, NotebookType } from '~/types'

import type { notebooksListLogicType } from './notebooksListLogicType'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import api from 'lib/api'
import posthog from 'posthog-js'
import { LOCAL_NOTEBOOK_TEMPLATES } from '../NotebookTemplates/notebookTemplates'
import { deleteWithUndo, objectClean, objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import FuseClass from 'fuse.js'
import { notebookPopoverLogic } from './notebookPopoverLogic'
import { EditorFocusPosition, JSONContent, defaultNotebookContent } from './utils'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { notebookLogicType } from 'scenes/notebooks/Notebook/notebookLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface Fuse extends FuseClass<NotebookListItemType> {}

export const SCRATCHPAD_NOTEBOOK: NotebookListItemType = {
    short_id: 'scratchpad',
    title: 'Scratchpad',
    created_at: '',
    created_by: null,
}

export const openNotebook = async (
    notebookId: string,
    target: NotebookTarget = NotebookTarget.Auto,
    focus: EditorFocusPosition = null,
    // operations to run against the notebook once it has opened and the editor is ready
    onOpen: (logic: BuiltLogic<notebookLogicType>) => void = () => {}
): Promise<void> => {
    const popoverLogic = notebookPopoverLogic.findMounted()

    if (NotebookTarget.Popover === target) {
        popoverLogic?.actions.setVisibility('visible')
    }

    if (popoverLogic?.values.visibility === 'visible') {
        popoverLogic?.actions.selectNotebook(notebookId)
    } else {
        router.actions.push(urls.notebookEdit(notebookId))
    }

    popoverLogic?.actions.setInitialAutofocus(focus)

    const theNotebookLogic = notebookLogic({ shortId: notebookId })
    const unmount = theNotebookLogic.mount()

    try {
        await theNotebookLogic.asyncActions.editorIsReady()
        onOpen(theNotebookLogic)
    } finally {
        unmount()
    }
}

export interface NotebooksListFilters {
    search: string
    // UUID of the user that created the notebook
    createdBy: string
    hasRecordings: boolean | string
}

export const DEFAULT_FILTERS: NotebooksListFilters = {
    search: '',
    createdBy: 'All users',
    hasRecordings: false,
}

function filtersToContains(
    filters?: NotebooksListFilters
): { type: NotebookNodeType; attrs: Record<string, string | boolean> }[] | undefined {
    if (filters === undefined || objectsEqual(filters, DEFAULT_FILTERS)) {
        return undefined
    }
    if (filters.hasRecordings) {
        return [{ type: NotebookNodeType.Recording, attrs: { present: filters.hasRecordings } }]
    }

    return undefined
}

async function listNotebooksAPI(filters?: NotebooksListFilters): Promise<NotebookListItemType[]> {
    // TODO: Support pagination
    const contains = filtersToContains(filters)
    const createdByForQuery = filters?.createdBy === DEFAULT_FILTERS.createdBy ? undefined : filters?.createdBy
    const res = await api.notebooks.list(contains, createdByForQuery)
    return res.results
}

export const notebooksListLogic = kea<notebooksListLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebooksListLogic']),
    actions({
        setScratchpadNotebook: (notebook: NotebookListItemType) => ({ notebook }),
        createNotebook: (
            title?: string,
            location: NotebookTarget = NotebookTarget.Auto,
            content?: JSONContent[],
            onCreate?: (notebook: NotebookType) => void
        ) => ({
            title,
            location,
            content,
            onCreate,
        }),
        receiveNotebookUpdate: (notebook: NotebookListItemType) => ({ notebook }),
        loadNotebooks: true,
        loadFilteredNotebooks: true,
        deleteNotebook: (shortId: NotebookListItemType['short_id'], title?: string) => ({ shortId, title }),
        setFilters: (filters: Partial<NotebooksListFilters>) => ({ filters }),
    }),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    reducers({
        filters: [
            DEFAULT_FILTERS as NotebooksListFilters,
            {
                setFilters: (state, { filters }) =>
                    objectClean({
                        ...(state || {}),
                        ...filters,
                    }),
            },
        ],

        scratchpadNotebook: [
            SCRATCHPAD_NOTEBOOK as NotebookListItemType,
            {
                setScratchpadNotebook: (_, { notebook }) => notebook,
            },
        ],

        filteredNotebooks: [
            [] as NotebookListItemType[],
            {
                // if we already have filtered notebooks, don't replace them
                loadNotebooksSuccess: (state, { notebooks }) => (!!state.length ? state : notebooks),
            },
        ],
    }),

    loaders(({ actions, values }) => ({
        filteredNotebooks: [
            [] as NotebookListItemType[],
            {
                loadFilteredNotebooks: async (_, breakpoint) => {
                    // the notebooks list logic is used in several components
                    // so, we can't just use the default loader when filtering
                    await breakpoint(100)
                    return await listNotebooksAPI(values.filters)
                },
            },
        ],
        notebooks: [
            [] as NotebookListItemType[],
            {
                loadNotebooks: async (_, breakpoint) => {
                    // TODO: Support pagination
                    await breakpoint(100)
                    return await listNotebooksAPI()
                },
                createNotebook: async ({ title, location, content, onCreate }, breakpoint) => {
                    await breakpoint(100)

                    const notebook = await api.notebooks.create({
                        title,
                        content: defaultNotebookContent(title, content),
                    })

                    openNotebook(notebook.short_id, location, 'end')

                    posthog.capture(`notebook created`, {
                        short_id: notebook.short_id,
                    })

                    onCreate?.(notebook)
                    return [notebook, ...values.notebooks]
                },

                deleteNotebook: async ({ shortId, title }) => {
                    deleteWithUndo({
                        endpoint: `projects/${values.currentTeamId}/notebooks`,
                        object: { name: title || shortId, id: shortId },
                        callback: actions.loadNotebooks,
                    })

                    notebookPopoverLogic.findMounted()?.actions.selectNotebook(SCRATCHPAD_NOTEBOOK.short_id)

                    return values.notebooks.filter((n) => n.short_id !== shortId)
                },

                receiveNotebookUpdate: ({ notebook }) => {
                    if (notebook.is_template) {
                        return values.notebooks
                    }
                    return values.notebooks.filter((n) => n.short_id !== notebook.short_id).concat([notebook])
                },
            },
        ],
        notebookTemplates: [
            LOCAL_NOTEBOOK_TEMPLATES as NotebookType[],
            {
                // In the future we can load these from remote
            },
        ],
    })),

    listeners(({ actions }) => ({
        setFilters: () => {
            actions.loadFilteredNotebooks()
        },
    })),

    selectors({
        fuse: [
            (s) => [s.notebooks],
            (notebooks): Fuse => {
                return new FuseClass<NotebookListItemType>(notebooks, {
                    keys: ['title'],
                    threshold: 0.3,
                })
            },
        ],
        searchFilteredNotebooks: [
            (s) => [s.filteredNotebooks, s.notebookTemplates, s.filters, s.fuse],
            (filteredNotebooks, notebooksTemplates, filters, fuse): NotebookListItemType[] => {
                const templatesToInclude: NotebookListItemType[] =
                    filters.createdBy === DEFAULT_FILTERS.createdBy ? [...notebooksTemplates] : []
                let haystack: NotebookListItemType[] = [...filteredNotebooks, ...templatesToInclude]

                if (filters.search) {
                    haystack = fuse.search(filters.search).map(({ item }) => item)
                }

                return haystack
            },
        ],
    }),
])
