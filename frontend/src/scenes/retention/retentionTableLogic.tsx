import { kea } from 'kea'
import api from 'lib/api'
import { errorToast, toParams } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionTableLogicType } from './retentionTableLogicType'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_TABLE, RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, InsightLogicProps, FilterType, InsightType, CohortType } from '~/types'
import {
    RetentionTablePayload,
    RetentionTrendPayload,
    RetentionTablePeoplePayload,
    RetentionTrendPeoplePayload,
    RetentionTableAppearanceType,
} from 'scenes/retention/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { teamLogic } from 'scenes/teamLogic'
import { toast } from 'react-toastify'
import React from 'react'
import { Link } from 'lib/components/Link'

export const dateOptions = ['Hour', 'Day', 'Week', 'Month']

export const retentionOptions = {
    [`${RETENTION_FIRST_TIME}`]: 'First Time',
    [`${RETENTION_RECURRING}`]: 'Recurring',
}

export const retentionOptionDescriptions = {
    [`${RETENTION_RECURRING}`]: 'A user will belong to any cohort where they have performed the event in its Period 0.',
    [`${RETENTION_FIRST_TIME}`]:
        'A user will only belong to the cohort for which they performed the event for the first time.',
}

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionTableLogic = kea<retentionTableLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'retentionTableLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['filters', 'insight', 'insightLoading'],
            actionsModel,
            ['actions'],
            teamLogic,
            ['currentTeamId'],
        ],
        actions: [insightLogic(props), ['loadResultsSuccess']],
    }),
    actions: () => ({
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        loadMorePeople: true,
        updatePeople: (people) => ({ people }),
        clearPeople: true,
        handleSaveCohort: true,
    }),
    loaders: ({ values }) => ({
        people: {
            __default: {} as RetentionTablePeoplePayload | RetentionTrendPeoplePayload,
            loadPeople: async (rowIndex: number) => {
                const urlParams = toParams({ ...values.filters, selected_interval: rowIndex })
                const res = await api.get(`api/person/retention/?${urlParams}`)
                return res
            },
        },
    }),
    reducers: {
        people: {
            clearPeople: () => ({}),
            updatePeople: (_, { people }) => people,
        },
        loadingMore: [
            false,
            {
                loadMorePeople: () => true,
                updatePeople: () => false,
            },
        ],
    },
    selectors: {
        loadedFilters: [
            (s) => [s.insight],
            ({ filters }): Partial<FilterType> => (filters?.insight === InsightType.RETENTION ? filters ?? {} : {}),
        ],
        results: [
            (s) => [s.insight],
            ({ filters, result }): RetentionTablePayload[] | RetentionTrendPayload[] => {
                return filters?.insight === InsightType.RETENTION &&
                    result &&
                    (result.length === 0 ||
                        (!result[0].values && filters.display === ACTIONS_LINE_GRAPH_LINEAR) ||
                        (result[0].values && filters.display === ACTIONS_TABLE))
                    ? result
                    : []
            },
        ],
        resultsLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
        actionsLookup: [
            (s) => [s.actions],
            (actions: ActionType[]) => Object.assign({}, ...actions.map((action) => ({ [action.id]: action.name }))),
        ],
        actionFilterTargetEntity: [(s) => [s.filters], (filters) => ({ events: [filters.target_entity] })],
        actionFilterReturningEntity: [(s) => [s.filters], (filters) => ({ events: [filters.returning_entity] })],
    },
    listeners: ({ actions, values, props }) => ({
        setProperties: ({ properties }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filters, properties }, values.filters))
        },
        setFilters: ({ filters }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filters, ...filters }, values.filters))
        },
        loadResultsSuccess: async () => {
            actions.clearPeople()
        },
        loadMorePeople: async () => {
            if (values.people.next) {
                const peopleResult = await api.get(values.people.next)
                const newPeople = {
                    result: [...(values.people.result as Record<string, any>[]), ...peopleResult['result']],
                    next: peopleResult['next'],
                }
                actions.updatePeople(newPeople)
            }
        },
        handleSaveCohort: async () => {
            // Create a cohort for the people displayed in the table.

            // NOTE: for now we just upload a static cohort using a csv, but
            // this doesn't scale well if we have lots of people in a cohort. So
            // we are just sending the people that we happen to have locally.
            //
            // For larger cohort sizes we'd need to find a different solution
            const result = values.people.result
            if (!result) {
                return
            }

            // NOTE: I couldn't figure out how to get narrowing here to remove
            // the `PersonType[]` union case
            const peopleAppearences = result as RetentionTableAppearanceType[]

            const formData = new FormData()
            const peopleCsvData = `
                user_id,
                ${peopleAppearences.flatMap(({ person }) => person.distinct_ids).join(',\n')}
            `
            const peopleCsvBlob = new Blob([peopleCsvData], { type: 'application/csv' })
            formData.append('csv', peopleCsvBlob, 'people.csv')

            // NOTE: we are not offering the user the ability to name before
            // creating the cohort. They can do this action as a cohort edit.
            formData.append('name', 'New retention cohort')
            formData.append('is_static', 'true')

            try {
                const savedCohort = await api.cohorts.create(formData as Partial<CohortType>)

                toast.success(
                    <div data-attr="success-toast">
                        <h1>Cohort saved successfully!</h1>
                        <p>
                            {/* Make sure we link to the new cohort, so the user can e.g. edit the name easily */}
                            <Link to={'/cohorts/' + savedCohort.id}>Click here to see the cohort.</Link>
                        </p>
                    </div>,
                    {
                        toastId: `cohort-saved-${savedCohort.id}`,
                    }
                )
            } catch (error: any) {
                errorToast(
                    'Error saving your cohort',
                    'Attempting to save this cohort returned an error:',
                    error.status !== 0
                        ? error.detail
                        : "Check your internet connection and make sure you don't have an extension blocking our requests.",
                    error.code
                )
                return
            }
        },
    }),
})
