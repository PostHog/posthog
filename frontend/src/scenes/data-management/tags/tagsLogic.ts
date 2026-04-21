import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { TagItemType, TagType } from '~/types'

import type { tagsLogicType } from './tagsLogicType'

export const tagsLogic = kea<tagsLogicType>([
    path(['scenes', 'data-management', 'tags', 'tagsLogic']),
    actions({
        setSearch: (search: string) => ({ search }),
        openMergeDialog: (source: TagType) => ({ source }),
        closeMergeDialog: true,
        openItemsDrawer: (tag: TagType) => ({ tag }),
        closeItemsDrawer: true,
        // Explicit action payloads for every loader so kea-loaders can infer the
        // correct action shape — destructuring inside the loader function alone
        // produces a payload type that conflicts with the state default.
        loadTags: true,
        createTag: (name: string) => ({ name }),
        renameTag: (id: string, name: string) => ({ id, name }),
        deleteTag: (id: string) => ({ id }),
        mergeTag: (sourceId: string, targetId: string) => ({ sourceId, targetId }),
        loadItemsForTag: (id: string) => ({ id }),
    }),
    reducers({
        search: [
            '' as string,
            {
                setSearch: (_, { search }) => search,
            },
        ],
        mergeDialogSource: [
            null as TagType | null,
            {
                openMergeDialog: (_, { source }) => source,
                closeMergeDialog: () => null,
            },
        ],
        itemsDrawerTag: [
            null as TagType | null,
            {
                openItemsDrawer: (_, { tag }) => tag,
                closeItemsDrawer: () => null,
            },
        ],
    }),
    loaders(({ values }) => ({
        tags: [
            [] as TagType[],
            {
                loadTags: async () => {
                    const response = await api.tags.listFull({ limit: 500 })
                    return response.results
                },
                createTag: async ({ name }) => {
                    const cleaned = name.trim().toLowerCase()
                    if (!cleaned) {
                        lemonToast.error('Tag name must not be empty.')
                        return values.tags
                    }
                    const created = await api.tags.create(cleaned)
                    lemonToast.success(`Created tag "${created.name}".`)
                    return [...values.tags, created].sort((a, b) => a.name.localeCompare(b.name))
                },
                renameTag: async ({ id, name }) => {
                    const cleaned = name.trim().toLowerCase()
                    if (!cleaned) {
                        lemonToast.error('Tag name must not be empty.')
                        return values.tags
                    }
                    const updated = await api.tags.update(id, cleaned)
                    lemonToast.success(`Renamed tag to "${updated.name}".`)
                    return values.tags
                        .map((tag) => (tag.id === id ? updated : tag))
                        .sort((a, b) => a.name.localeCompare(b.name))
                },
                deleteTag: async ({ id }) => {
                    await api.tags.delete(id)
                    lemonToast.success('Tag deleted.')
                    return values.tags.filter((tag) => tag.id !== id)
                },
                mergeTag: async ({ sourceId, targetId }) => {
                    const merged = await api.tags.merge(sourceId, targetId)
                    lemonToast.success(`Merged into "${merged.name}".`)
                    return values.tags
                        .filter((tag) => tag.id !== sourceId)
                        .map((tag) => (tag.id === merged.id ? merged : tag))
                },
            },
        ],
        itemsForTag: [
            [] as TagItemType[],
            {
                loadItemsForTag: async ({ id }) => {
                    return await api.tags.items(id)
                },
            },
        ],
    })),
    selectors({
        filteredTags: [
            (s) => [s.tags, s.search],
            (tags, search): TagType[] => {
                if (!search) {
                    return tags
                }
                const needle = search.trim().toLowerCase()
                return tags.filter((tag) => tag.name.includes(needle))
            },
        ],
    }),
    listeners(({ actions }) => ({
        openItemsDrawer: ({ tag }) => {
            actions.loadItemsForTag(tag.id)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTags()
    }),
])
