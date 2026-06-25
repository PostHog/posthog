import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { experimentsList, experimentsRetrieve } from 'products/experiments/frontend/generated/api'
import type { ExperimentApi, ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'

import type { experimentPickerLogicType } from './experimentPickerLogicType'

/** One page is plenty — search narrows the rest server-side, so we never paginate the dropdown. */
const EXPERIMENT_OPTIONS_LIMIT = 50
const SEARCH_DEBOUNCE_MS = 300

export type ExperimentPickerLogicProps = { pickerKey: string }

export const experimentPickerLogic = kea<experimentPickerLogicType>([
    path((key) => ['products', 'dashboards', 'widgets', 'experiments', 'experimentPickerLogic', key]),
    props({} as ExperimentPickerLogicProps),
    key((props) => props.pickerKey),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setSearch: (search: string) => ({ search }),
        ensureOptionsLoaded: true,
        ensureSelectedLoaded: (experimentId: number) => ({ experimentId }),
    }),

    reducers({
        search: ['', { setSearch: (_: string, { search }: { search: string }) => search }],
        hasLoadedOptions: [false, { loadOptionsSuccess: () => true }],
    }),

    loaders(({ values }) => ({
        experimentOptions: [
            [] as ExperimentBasicApi[],
            {
                loadOptions: async (
                    { debounce }: { debounce: boolean } = { debounce: false },
                    breakpoint
                ): Promise<ExperimentBasicApi[]> => {
                    // Debounce keystroke-driven searches; the initial focus load should open the dropdown immediately.
                    if (debounce) {
                        await breakpoint(SEARCH_DEBOUNCE_MS)
                    }
                    const response = await experimentsList(String(values.currentProjectId), {
                        limit: EXPERIMENT_OPTIONS_LIMIT,
                        order: '-created_at',
                        search: values.search || undefined,
                    })
                    breakpoint()
                    return response.results ?? []
                },
            },
        ],
        selectedExperiment: [
            null as ExperimentApi | null,
            {
                loadSelectedExperiment: async ({ experimentId }: { experimentId: number }): Promise<ExperimentApi> =>
                    experimentsRetrieve(String(values.currentProjectId), experimentId),
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        setSearch: () => {
            actions.loadOptions({ debounce: true })
        },
        ensureOptionsLoaded: () => {
            if (!values.hasLoadedOptions && !values.experimentOptionsLoading) {
                actions.loadOptions({ debounce: false })
            }
        },
        ensureSelectedLoaded: ({ experimentId }) => {
            if (values.selectedExperiment?.id === experimentId || values.selectedExperimentLoading) {
                return
            }
            actions.loadSelectedExperiment({ experimentId })
        },
    })),
])
