import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'
import { cohortsModel } from '~/models/cohortsModel'
import { ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'
import { cohortLogicType } from './cohortLogicType'
import { Breadcrumb, CohortGroupType, CohortType } from '~/types'
import { convertPropertyGroupToProperties } from 'lib/utils'
import { personsLogic } from 'scenes/persons/personsLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'
import { actionToUrl } from 'kea-router'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

function createCohortFormData(cohort: CohortType): FormData {
    const rawCohort = {
        ...(cohort.name ? { name: cohort.name } : {}),
        ...(cohort.description ? { description: cohort.description } : {}),
        ...(cohort.csv ? { csv: cohort.csv } : {}),
        ...(cohort.is_static ? { is_static: cohort.is_static } : {}),
        groups: JSON.stringify(
            cohort.is_static
                ? []
                : cohort.groups.map((group: CohortGroupType) => ({ ...group, id: undefined, matchType: undefined }))
        ),
    }
    // Must use FormData to encode file binary in request
    const cohortFormData = new FormData()
    for (const [itemKey, value] of Object.entries(rawCohort)) {
        cohortFormData.append(itemKey, value as string | Blob)
    }
    return cohortFormData
}

function addLocalCohortGroupId(group: Partial<CohortGroupType>): CohortGroupType {
    const matchType = group.action_id || group.event_id ? ENTITY_MATCH_TYPE : PROPERTY_MATCH_TYPE

    return {
        matchType,
        id: Math.random().toString().substr(2, 5),
        ...group,
    }
}

function processCohortOnSet(cohort: CohortType): CohortType {
    if (cohort.groups) {
        cohort.groups = cohort.groups.map((group) => addLocalCohortGroupId(group))
        cohort.groups = cohort.groups.map((group) => {
            if (group.properties) {
                return {
                    ...group,
                    properties: convertPropertyGroupToProperties(group.properties),
                }
            }
            return group
        })
    }

    return cohort
}

export const NEW_COHORT: CohortType = processCohortOnSet({
    id: 'new',
    groups: [
        {
            id: Math.random().toString().substr(2, 5),
            matchType: PROPERTY_MATCH_TYPE,
            properties: [],
        },
    ],
})

export interface CohortLogicProps {
    id?: CohortType['id']
}

export const cohortLogic = kea<cohortLogicType<CohortLogicProps>>([
    props({} as CohortLogicProps),
    key((props) => props.id || 'new'),
    path(['scenes', 'cohorts', 'cohortLogic']),

    actions({
        saveCohort: (cohortParams = {}) => ({ cohortParams }),
        setCohort: (cohort: CohortType) => ({ cohort }),
        deleteCohort: true,
        fetchCohort: (id: CohortType['id']) => ({ id }),
        onCriteriaChange: (newGroup: Partial<CohortGroupType>, id: string) => ({ newGroup, id }),
        setPollTimeout: (pollTimeout: NodeJS.Timeout | null) => ({ pollTimeout }),
        checkIfFinishedCalculating: (cohort: CohortType) => ({ cohort }),
    }),

    reducers(() => ({
        cohort: [
            NEW_COHORT as CohortType,
            {
                onCriteriaChange: (state, { newGroup, id }) => {
                    const cohort = { ...state }
                    const index = cohort.groups.findIndex((group: CohortGroupType) => group.id === id)
                    if (newGroup.matchType) {
                        cohort.groups[index] = {
                            id: cohort.groups[index].id,
                            matchType: ENTITY_MATCH_TYPE,
                            ...newGroup,
                        }
                    } else {
                        cohort.groups[index] = {
                            ...cohort.groups[index],
                            ...newGroup,
                        }
                    }
                    return processCohortOnSet(cohort)
                },
            },
        ],
        pollTimeout: [
            null as NodeJS.Timeout | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
    })),

    forms(({ actions }) => ({
        cohort: {
            defaults: NEW_COHORT,
            errors: ({ name, csv, is_static, groups }) => ({
                name: !name ? 'You need to set a name' : undefined,
                csv: is_static && !csv ? 'You need to upload a CSV file' : (null as any),
                // Return type of validator[groups](...) must be the shape of groups. Returning the error message
                // for groups as a value for id is a hacky stopgap.
                groups: is_static
                    ? undefined
                    : !groups || groups.length < 1
                    ? [{ id: 'You need at least one matching group' }]
                    : groups?.map(({ matchType, properties, action_id, event_id }) => {
                          if (matchType === PROPERTY_MATCH_TYPE && !properties?.length) {
                              return { id: 'Please select at least one property or remove this match group.' }
                          }
                          if (matchType === ENTITY_MATCH_TYPE && !(action_id || event_id)) {
                              return { id: 'Please select an event or action.' }
                          }
                          return { id: undefined }
                      }),
            }),
            submit: (cohort) => {
                actions.saveCohort(cohort)
            },
        },
    })),

    loaders(({ actions, values, key }) => ({
        cohort: [
            NEW_COHORT as CohortType,
            {
                setCohort: ({ cohort }) => {
                    return processCohortOnSet(cohort)
                },
                fetchCohort: async ({ id }, breakpoint) => {
                    try {
                        const cohort = await api.cohorts.get(id)
                        breakpoint()
                        cohortsModel.actions.updateCohort(cohort)
                        actions.checkIfFinishedCalculating(cohort)
                        return processCohortOnSet(cohort)
                    } catch (error: any) {
                        lemonToast.error(error.detail || 'Failed to fetch cohort')
                        return values.cohort
                    }
                },
                saveCohort: async ({ cohortParams }, breakpoint) => {
                    let cohort = { ...cohortParams }

                    const cohortFormData = createCohortFormData(cohort)

                    try {
                        if (cohort.id !== 'new') {
                            cohort = await api.cohorts.update(cohort.id, cohortFormData as Partial<CohortType>)
                            cohortsModel.actions.updateCohort(cohort)
                        } else {
                            cohort = await api.cohorts.create(cohortFormData as Partial<CohortType>)
                            cohortsModel.actions.cohortCreated(cohort)
                        }
                    } catch (error: any) {
                        breakpoint()
                        lemonToast.error(error.detail || 'Failed to save cohort')
                        return values.cohort
                    }

                    cohort.is_calculating = true // this will ensure there is always a polling period to allow for backend calculation task to run
                    breakpoint()
                    delete cohort['csv']
                    actions.setCohort(cohort)
                    lemonToast.success('Cohort saved. Please wait up to a few minutes for it to be calculated', {
                        toastId: `cohort-saved-${key}`,
                    })
                    actions.checkIfFinishedCalculating(cohort)
                    return cohort
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.cohort],
            (cohort): Breadcrumb[] => [
                {
                    name: 'Cohorts',
                    path: urls.cohorts(),
                },
                ...(cohort ? [{ name: cohort.name || 'Untitled' }] : []),
            ],
        ],
    }),

    listeners(({ actions, values }) => ({
        deleteCohort: () => {
            cohortsModel.findMounted()?.actions.deleteCohort(values.cohort)
            router.actions.push(urls.cohorts())
        },
        checkIfFinishedCalculating: async ({ cohort }, breakpoint) => {
            if (cohort.is_calculating) {
                actions.setPollTimeout(
                    setTimeout(async () => {
                        const newCohort = await api.cohorts.get(cohort.id)
                        breakpoint()
                        actions.checkIfFinishedCalculating(newCohort)
                    }, 1000)
                )
            } else {
                actions.setCohort(cohort)
                cohortsModel.actions.updateCohort(cohort)
                personsLogic.findMounted({ syncWithUrl: true })?.actions.loadCohorts() // To ensure sync on person page
                if (values.pollTimeout) {
                    clearTimeout(values.pollTimeout)
                    actions.setPollTimeout(null)
                }
            }
        },
    })),

    actionToUrl(({ values }) => ({
        saveCohortSuccess: () => urls.cohort(values.cohort.id),
    })),

    afterMount(({ actions, props }) => {
        if (!props.id || props.id === 'new') {
            actions.setCohort(NEW_COHORT)
        } else {
            actions.fetchCohort(props.id)
        }
    }),
    beforeUnmount(({ values }) => {
        if (values.pollTimeout) {
            clearTimeout(values.pollTimeout)
        }
    }),
])
