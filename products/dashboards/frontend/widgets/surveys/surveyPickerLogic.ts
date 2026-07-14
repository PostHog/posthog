import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { surveysList, surveysRetrieve } from 'products/surveys/frontend/generated/api'
import type { SurveyApi } from 'products/surveys/frontend/generated/api.schemas'

import type { surveyPickerLogicType } from './surveyPickerLogicType'

/** One page is plenty — search narrows the rest server-side, so we never paginate the dropdown. */
const SURVEY_OPTIONS_LIMIT = 50
const SEARCH_DEBOUNCE_MS = 300

export type SurveyPickerLogicProps = {
    pickerKey: string
    /** When set, the logic resolves this survey's name on mount/change — lets read-only callers show it without a component effect. */
    ensureSurveyId?: string | null
}

export const surveyPickerLogic = kea<surveyPickerLogicType>([
    path((key) => ['products', 'dashboards', 'widgets', 'surveys', 'surveyPickerLogic', key]),
    props({} as SurveyPickerLogicProps),
    key((props) => props.pickerKey),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setSearch: (search: string) => ({ search }),
        ensureOptionsLoaded: true,
        ensureSelectedLoaded: (surveyId: string) => ({ surveyId }),
    }),

    reducers({
        search: ['', { setSearch: (_: string, { search }: { search: string }) => search }],
        hasLoadedOptions: [false, { loadOptionsSuccess: () => true }],
    }),

    loaders(({ values }) => ({
        surveyOptions: [
            [] as SurveyApi[],
            {
                loadOptions: async (
                    { debounce }: { debounce: boolean } = { debounce: false },
                    breakpoint
                ): Promise<SurveyApi[]> => {
                    // Debounce keystroke-driven searches; the initial focus load should open the dropdown immediately.
                    if (debounce) {
                        await breakpoint(SEARCH_DEBOUNCE_MS)
                    }
                    const response = await surveysList(String(values.currentProjectId), {
                        limit: SURVEY_OPTIONS_LIMIT,
                        search: values.search || undefined,
                    })
                    breakpoint()
                    return response.results ?? []
                },
            },
        ],
        selectedSurvey: [
            null as SurveyApi | null,
            {
                loadSelectedSurvey: async ({ surveyId }: { surveyId: string }): Promise<SurveyApi> =>
                    surveysRetrieve(String(values.currentProjectId), surveyId),
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        setSearch: () => {
            actions.loadOptions({ debounce: true })
        },
        ensureOptionsLoaded: () => {
            if (!values.hasLoadedOptions && !values.surveyOptionsLoading) {
                actions.loadOptions({ debounce: false })
            }
        },
        ensureSelectedLoaded: ({ surveyId }) => {
            if (values.selectedSurvey?.id === surveyId || values.selectedSurveyLoading) {
                return
            }
            actions.loadSelectedSurvey({ surveyId })
        },
    })),

    afterMount(({ props, actions }) => {
        if (props.ensureSurveyId) {
            actions.ensureSelectedLoaded(props.ensureSurveyId)
        }
    }),

    propsChanged(({ props, actions }, oldProps) => {
        if (props.ensureSurveyId && props.ensureSurveyId !== oldProps.ensureSurveyId) {
            actions.ensureSelectedLoaded(props.ensureSurveyId)
        }
    }),
])
