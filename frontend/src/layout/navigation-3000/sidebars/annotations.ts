import { connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { annotationsModel } from '~/models/annotationsModel'
import { SidebarCategory, ExtendedListItem } from '../types'
import type { annotationsSidebarLogicType } from './annotationsType'
import Fuse from 'fuse.js'
import { subscriptions } from 'kea-subscriptions'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { FuseSearchMatch } from './utils'
import { AnnotationType } from '~/types'
import { urls } from '@posthog/apps-common'

const fuse = new Fuse<AnnotationType>([], {
    keys: [{ name: 'content', weight: 2 }, 'date_marker'],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

export const annotationsSidebarLogic = kea<annotationsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'annotationsSidebarLogic']),
    connect({
        values: [annotationsModel, ['annotations', 'annotationsLoading'], sceneLogic, ['activeScene', 'sceneParams']],
        actions: [annotationsModel, ['deleteAnnotation']],
    }),
    selectors(({ actions }) => ({
        contents: [
            (s) => [s.relevantAnnotations, s.annotationsLoading],
            (relevantAnnotations, annotationsLoading) => [
                {
                    key: 'annotations',
                    title: 'Annotations',
                    // TODO: Add onAdd opening modal
                    items: relevantAnnotations.map(
                        ([annotation, matches]) =>
                            ({
                                key: annotation.id,
                                name: annotation.content,
                                summary: annotation.date_marker?.format('MMM D, YYYY h:mm A') || 'unknown date',
                                url: urls.annotation(annotation.id),
                                searchMatch: matches
                                    ? {
                                          matchingFields: matches.map((match) => match.key),
                                          nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                                      }
                                    : null,
                                menuItems: [
                                    {
                                        items: [
                                            {
                                                onClick: () => {
                                                    actions.deleteAnnotation(annotation)
                                                },
                                                status: 'danger',
                                                label: 'Delete annotation',
                                            },
                                        ],
                                    },
                                ],
                                extraContextTop: annotation.created_at,
                                extraContextBottom: `by ${annotation.created_by?.first_name}`,
                            } as ExtendedListItem)
                    ),
                    loading: annotationsLoading,
                } as SidebarCategory,
            ],
        ],
        relevantAnnotations: [
            (s) => [s.annotations, navigation3000Logic.selectors.searchTerm],
            (annotations, searchTerm): [AnnotationType, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return fuse.search(searchTerm).map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return annotations.map((annotation) => [annotation, null])
            },
        ],
    })),
    subscriptions({
        annotations: (annotations) => {
            fuse.setCollection(annotations)
        },
    }),
])
