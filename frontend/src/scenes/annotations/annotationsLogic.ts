import { LemonSelectOption, LemonSelectOptions } from '@posthog/lemon-ui'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationScope, AnnotationType } from '~/types'

import { annotationScopeToName } from './annotationModalLogic'
import type { annotationsLogicType } from './annotationsLogicType'

export const annotationsLogic = kea<annotationsLogicType>([
    path(['scenes', 'annotations', 'annotationsLogic']),
    connect(() => ({
        actions: [
            annotationsModel,
            [
                'loadAnnotationsNext',
                'loadAnnotationsSuccess',
                'replaceAnnotation',
                'appendAnnotations',
                'deleteAnnotation',
            ],
        ],
        values: [
            annotationsModel,
            ['annotations', 'annotationsLoading', 'next', 'loadingNext'],
            teamLogic,
            ['timezone'],
            userLogic,
            ['user'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions({
        setScope: (scope: AnnotationType['scope'] | null) => ({ scope }),
    }),
    reducers(() => ({
        scope: [null as AnnotationType['scope'] | null, { setScope: (_, { scope }) => scope }],
    })),
    selectors(() => ({
        shouldShowEmptyState: [
            (s) => [s.annotations, s.annotationsLoading],
            (annotations, annotationsLoading): boolean => {
                return annotations.length === 0 && !annotationsLoading
            },
        ],
        allowRecordingScope: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => {
                return !!featureFlags[FEATURE_FLAGS.ANNOTATIONS_RECORDING_SCOPE]
            },
        ],
        scopeOptions: [
            (s) => [s.allowRecordingScope],
            (allowRecordingScope): LemonSelectOptions<AnnotationType['scope'] | null> => {
                const scopes = Object.values(AnnotationScope).filter((scope) => {
                    return allowRecordingScope ? true : scope !== AnnotationScope.Recording
                })
                const scopeOptions: LemonSelectOption<AnnotationType['scope'] | null>[] = scopes.map((scope) => ({
                    value: scope,
                    label: annotationScopeToName[scope],
                }))
                // add any with value null as the first option
                scopeOptions.unshift({
                    value: null,
                    label: 'Any',
                })
                return scopeOptions
            },
        ],
        filteredAnnotations: [
            (s) => [s.annotations, s.scope],
            (annotations, scope): AnnotationType[] => {
                return scope
                    ? annotations.filter((annotation) => {
                          return annotation.scope === scope
                      })
                    : annotations
            },
        ],
    })),
])
