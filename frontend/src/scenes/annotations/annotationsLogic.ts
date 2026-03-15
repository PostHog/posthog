import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { LemonSelectOption, LemonSelectOptions } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationScope, AnnotationType } from '~/types'

import { annotationScopeToName } from './annotationModalLogic'
import type { annotationsLogicType } from './annotationsLogicType'

const isValidAnnotationScope = (scope: string): scope is AnnotationScope => {
    return Object.values(AnnotationScope).includes(scope as AnnotationScope)
}

export const annotationScopesMenuOptions = (): LemonSelectOptions<AnnotationType['scope'] | null> => {
    const scopeOptions: LemonSelectOption<AnnotationType['scope'] | null>[] = Object.values(AnnotationScope).map(
        (scope) => ({
            value: scope,
            label: annotationScopeToName[scope],
        })
    )
    // add any with value null as the first option
    scopeOptions.unshift({
        value: null,
        label: 'Any',
    })
    return scopeOptions
}

export const annotationsLogic = kea<annotationsLogicType>([
    path(['scenes', 'annotations', 'annotationsLogic']),
    connect(() => ({
        values: [
            annotationsModel,
            ['annotations', 'annotationsLoading', 'next', 'loadingNext'],
            teamLogic,
            ['timezone'],
        ],
    })),
    actions({
        setScope: (scope: AnnotationType['scope'] | null) => ({ scope }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setFilterByTag: (tag: string | null) => ({ tag }),
    }),
    reducers(() => ({
        scope: [null as AnnotationType['scope'] | null, { setScope: (_, { scope }) => scope }],
        searchTerm: ['' as string, { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        filterByTag: [null as string | null, { setFilterByTag: (_, { tag }) => tag }],
    })),
    selectors(() => ({
        shouldShowEmptyState: [
            (s) => [s.annotations, s.annotationsLoading],
            (annotations, annotationsLoading): boolean => {
                return annotations.length === 0 && !annotationsLoading
            },
        ],
        allTags: [
            (s) => [s.annotations],
            (annotations): string[] => {
                const tagSet = new Set<string>()
                for (const annotation of annotations) {
                    for (const tag of annotation.tags || []) {
                        tagSet.add(tag)
                    }
                }
                return Array.from(tagSet).sort()
            },
        ],
        filteredAnnotations: [
            (s) => [s.annotations, s.scope, s.searchTerm, s.filterByTag],
            (annotations, scope, searchTerm, filterByTag): AnnotationType[] => {
                let result = annotations
                if (scope) {
                    result = result.filter((annotation) => annotation.scope === scope)
                }
                if (searchTerm.trim()) {
                    const term = searchTerm.trim().toLowerCase()
                    result = result.filter(
                        (annotation) => annotation.content && annotation.content.toLowerCase().includes(term)
                    )
                }
                if (filterByTag) {
                    result = result.filter((annotation) => annotation.tags && annotation.tags.includes(filterByTag))
                }
                return result
            },
        ],
    })),
    actionToUrl(() => ({
        setScope: ({ scope }) => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    scope: scope ? scope : undefined,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
        setSearchTerm: ({ searchTerm }) => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    q: searchTerm ? searchTerm : undefined,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
        setFilterByTag: ({ tag }) => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    tag: tag ? tag : undefined,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.annotations()]: (_, searchParams) => {
            const scope = searchParams.scope
            if (scope && isValidAnnotationScope(scope) && scope !== values.scope) {
                actions.setScope(scope)
            }
            if (!scope && values.scope) {
                actions.setScope(null)
            }
            const q = searchParams.q
            if (q !== undefined && q !== values.searchTerm) {
                actions.setSearchTerm(q)
            }
            if (!q && values.searchTerm) {
                actions.setSearchTerm('')
            }
            const tag = searchParams.tag
            if (tag !== undefined && tag !== values.filterByTag) {
                actions.setFilterByTag(tag)
            }
            if (!tag && values.filterByTag) {
                actions.setFilterByTag(null)
            }
        },
    })),
])
