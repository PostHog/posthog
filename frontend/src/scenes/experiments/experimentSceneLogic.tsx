import { BuiltLogic, actions, kea, listeners, path, props, reducers, selectors } from 'kea'

import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, Experiment, ProjectTreeRef } from '~/types'

import {
    type ExperimentLogicProps,
    FORM_MODES,
    type FormModes,
    NEW_EXPERIMENT,
    experimentLogic,
} from './experimentLogic'
import type { experimentLogicType } from './experimentLogicType'
import type { experimentSceneLogicType } from './experimentSceneLogicType'

export interface ExperimentSceneLogicProps extends ExperimentLogicProps {
    tabId?: string
}

export const experimentSceneLogic = kea<experimentSceneLogicType>([
    props({} as ExperimentSceneLogicProps),
    path(['scenes', 'experiments', 'experimentSceneLogic']),
    tabAwareScene(),
    actions({
        setActiveTabKey: (activeTabKey: string) => ({ activeTabKey }),
        setSceneState: (experimentId: Experiment['id'], formMode: FormModes) => ({ experimentId, formMode }),
        setExperimentLogicRef: (
            logic: BuiltLogic<experimentLogicType> | null,
            unmount: null | (() => void),
            logicProps: ExperimentLogicProps | null
        ) => ({
            logic,
            unmount,
            logicProps,
        }),
        setEditMode: (editing: boolean) => ({ editing }),
        resetExperimentState: (experimentConfig: Experiment) => ({ experimentConfig }),
        loadExperimentData: true,
        loadExposuresData: (forceRefresh: boolean = false) => ({ forceRefresh }),
    }),
    reducers({
        activeTabKey: [
            'metrics' as string,
            {
                setActiveTabKey: (_, { activeTabKey }) => activeTabKey,
            },
        ],
        experimentId: [
            (props: ExperimentSceneLogicProps) => props.experimentId ?? 'new',
            {
                setSceneState: (_, { experimentId }) => experimentId,
            },
        ],
        formMode: [
            (props: ExperimentSceneLogicProps) => props.formMode ?? FORM_MODES.update,
            {
                setSceneState: (_, { formMode }) => formMode,
            },
        ],
        experimentLogicRef: [
            null as null | {
                logic: BuiltLogic<experimentLogicType>
                unmount: () => void
                props: ExperimentLogicProps
            },
            {
                setExperimentLogicRef: (_, { logic, unmount, logicProps }) =>
                    logic && unmount && logicProps ? { logic, unmount, props: logicProps } : null,
            },
        ],
    }),
    selectors({
        tabId: [() => [(_, props) => props.tabId], (tabId: string | undefined): string | undefined => tabId],
        experimentSelector: [
            (s) => [s.experimentLogicRef],
            (experimentLogicRef) => experimentLogicRef?.logic.selectors.experiment,
        ],
        experiment: [
            (s) => [
                (state, props) => {
                    try {
                        return s.experimentSelector?.(state, props)?.(state, props)
                    } catch {
                        return null
                    }
                },
            ],
            (experiment): Experiment => (experiment ?? NEW_EXPERIMENT) as Experiment,
        ],
        experimentMissingSelector: [
            (s) => [s.experimentLogicRef],
            (experimentLogicRef) => experimentLogicRef?.logic.selectors.experimentMissing,
        ],
        experimentMissing: [
            (s) => [
                (state, props) => {
                    try {
                        return s.experimentMissingSelector?.(state, props)?.(state, props)
                    } catch {
                        return false
                    }
                },
            ],
            (experimentMissing): boolean => experimentMissing ?? false,
        ],
        isExperimentRunningSelector: [
            (s) => [s.experimentLogicRef],
            (experimentLogicRef) => experimentLogicRef?.logic.selectors.isExperimentRunning,
        ],
        isExperimentRunning: [
            (s) => [
                (state, props) => {
                    try {
                        return s.isExperimentRunningSelector?.(state, props)?.(state, props)
                    } catch {
                        return false
                    }
                },
            ],
            (isExperimentRunning): boolean => isExperimentRunning ?? false,
        ],
        breadcrumbs: [
            (s) => [s.experiment, s.experimentId],
            (experiment: Experiment, experimentId: Experiment['id']): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Experiments,
                        name: sceneConfigurations[Scene.Experiments].name || 'Experiments',
                        path: urls.experiments(),
                        iconType: sceneConfigurations[Scene.Experiments].iconType || 'default_icon_type',
                    },
                    {
                        key: [Scene.Experiment, experimentId],
                        name: experiment?.name || 'New Experiment',
                        iconType: sceneConfigurations[Scene.Experiment].iconType || 'default_icon_type',
                    },
                ]
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.experimentId],
            (experimentId: Experiment['id']): SidePanelSceneContext | null => {
                return experimentId && experimentId !== 'new'
                    ? {
                          activity_scope: ActivityScope.EXPERIMENT,
                          activity_item_id: `${experimentId}`,
                      }
                    : null
            },
        ],
        projectTreeRef: [
            (s) => [s.experimentId],
            (experimentId: Experiment['id']): ProjectTreeRef => {
                return { type: 'experiment', ref: experimentId === 'new' ? null : String(experimentId) }
            },
        ],
    }),
    listeners(({ actions, values }) => {
        const ensureExperimentLogicMounted = (): void => {
            if (!values.tabId) {
                throw new Error('Tab-aware scene logic must have a tabId prop')
            }

            const currentProps = values.experimentLogicRef?.props
            const desiredExperimentId = values.experimentId ?? 'new'
            const desiredFormMode = values.formMode ?? FORM_MODES.update

            if (
                !values.experimentLogicRef ||
                currentProps?.experimentId !== desiredExperimentId ||
                currentProps?.formMode !== desiredFormMode ||
                currentProps?.tabId !== values.tabId
            ) {
                const oldRef = values.experimentLogicRef

                const logicProps: ExperimentLogicProps = {
                    experimentId: desiredExperimentId,
                    formMode: desiredFormMode,
                    tabId: values.tabId,
                }

                const logic = experimentLogic.build(logicProps)
                const unmount = logic.mount()
                actions.setExperimentLogicRef(logic, unmount, logicProps)

                if (oldRef) {
                    oldRef.unmount()
                }
            }
        }

        return {
            setSceneState: () => {
                ensureExperimentLogicMounted()
            },
            setEditMode: ({ editing }) => {
                ensureExperimentLogicMounted()
                values.experimentLogicRef?.logic.actions.setEditExperiment(editing)
            },
            resetExperimentState: ({ experimentConfig }) => {
                ensureExperimentLogicMounted()
                values.experimentLogicRef?.logic.actions.resetExperiment(experimentConfig)
            },
            loadExperimentData: () => {
                ensureExperimentLogicMounted()
                values.experimentLogicRef?.logic.actions.loadExperiment()
            },
            loadExposuresData: ({ forceRefresh }) => {
                ensureExperimentLogicMounted()
                values.experimentLogicRef?.logic.actions.loadExposures(forceRefresh)
            },
        }
    }),
    tabAwareActionToUrl(({ values }) => {
        const actionToUrl = ({
            experimentId = values.experimentId,
            formMode = values.formMode,
        }: {
            experimentId?: Experiment['id']
            formMode?: FormModes
        }):
            | [string, Record<string, any> | string | undefined, Record<string, any> | string | undefined]
            | undefined => {
            const id = experimentId ?? 'new'
            const effectiveFormMode =
                id === 'new' && formMode === FORM_MODES.create
                    ? undefined
                    : formMode === FORM_MODES.update
                      ? undefined
                      : formMode

            return [urls.experiment(id, effectiveFormMode), undefined, undefined]
        }

        return {
            setSceneState: actionToUrl,
        }
    }),
    tabAwareUrlToAction(({ actions, values }) => ({
        '/experiments/:id': ({ id }, query, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            actions.setEditMode(false)

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                const formMode = parsedId === 'new' ? FORM_MODES.create : FORM_MODES.update
                const existingProps = values.experimentLogicRef?.props
                const matchesExistingLogic =
                    existingProps?.experimentId === parsedId && existingProps?.formMode === formMode

                actions.setSceneState(parsedId, formMode)

                if (parsedId === 'new') {
                    // Only reset if we're not already viewing a new experiment (tab switch scenario)
                    const shouldReset = currentLocation.initial || values.experimentId !== 'new'

                    if (shouldReset) {
                        actions.resetExperimentState({
                            ...NEW_EXPERIMENT,
                            metrics: query.metric ? [query.metric] : [],
                            name: query.name ?? '',
                        })
                    }
                } else {
                    // Only load if this is a different experiment or we have no cached logic yet
                    const shouldLoad = currentLocation.initial || !matchesExistingLogic

                    if (shouldLoad) {
                        actions.loadExperimentData()
                        if (values.isExperimentRunning) {
                            actions.loadExposuresData()
                        }
                    }
                }
            }
        },
        '/experiments/:id/:formMode': ({ id, formMode }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                const parsedFormMode =
                    formMode && Object.values(FORM_MODES).includes(formMode as FormModes)
                        ? (formMode as FormModes)
                        : parsedId === 'new'
                          ? FORM_MODES.create
                          : FORM_MODES.update
                const existingProps = values.experimentLogicRef?.props
                const matchesExistingLogic =
                    existingProps?.experimentId === parsedId && existingProps?.formMode === parsedFormMode

                actions.setSceneState(parsedId, parsedFormMode)

                // For form modes, always reload to ensure proper data transformation (duplicate/edit)
                // unless we're just switching back to a tab that already has this exact experiment+formMode loaded
                const shouldLoad = currentLocation.initial || !matchesExistingLogic

                if (shouldLoad) {
                    actions.loadExperimentData()
                }
            }
        },
    })),
])
