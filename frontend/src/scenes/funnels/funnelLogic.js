import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { objectsEqual, toParams } from 'lib/utils'

function wait(ms = 1000) {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

const SECONDS_TO_POLL = 120

export async function pollFunnel(id, params = {}) {
    let result = await api.get('api/funnel/' + id + '/?' + toParams(params))
    let count = 0
    while (result.loading && count < SECONDS_TO_POLL) {
        await wait()
        result = await api.get('api/funnel/' + id)
        count += 1
    }
    // if endpoint is still loading after 2 minutes just return default
    if (result.loading) {
        result = { filters: {} }
    }
    return result
}

export const funnelLogic = kea({
    key: (props) => props.id || 'new',

    actions: () => ({
        setFunnel: (funnel, update) => ({ funnel, update }),
        clearFunnel: true,
    }),

    connect: {
        actions: [insightLogic, ['setAllFilters']],
    },

    loaders: ({ props }) => ({
        funnel: [
            { filters: {} },
            {
                loadFunnel: async (id = props.id) => {
                    return await pollFunnel(id)
                },
                updateFunnel: async (funnel) => {
                    await api.update('api/funnel/' + funnel.id, funnel)

                    return await pollFunnel(funnel.id, { refresh: true })
                },
                createFunnel: async (funnel) => {
                    const newFunnel = await api.create('api/funnel', funnel)
                    return await pollFunnel(newFunnel.id, { refresh: true })
                },
            },
        ],
        people: {
            loadPeople: async (steps) => {
                return (await api.get('api/person/?id=' + steps[0].people.join(','))).results
            },
        },
    }),

    reducers: () => ({
        funnel: {
            setFunnel: (state, { funnel }) => ({
                ...state,
                ...funnel,
                filters: { ...state.filters, ...funnel.filters },
            }),
            clearFunnel: () => ({ filters: {} }),
        },
        people: {
            clearFunnel: () => null,
        },
    }),

    selectors: ({ selectors }) => ({
        stepsWithCount: [() => [selectors.funnel], (funnel) => funnel.steps],
        peopleSorted: [
            () => [selectors.stepsWithCount, selectors.people],
            (steps, people) => {
                if (!people) return null
                const score = (person) => {
                    return steps.reduce((val, step) => (step.people.indexOf(person.id) > -1 ? val + 1 : val), 0)
                }
                return people.sort((a, b) => score(b) - score(a))
            },
        ],
        isStepsEmpty: [
            () => [selectors.funnel],
            (funnel) => {
                return funnel && [...(funnel.filters.actions || []), ...(funnel.filters.events || [])].length === 0
            },
        ],
    }),

    listeners: ({ actions, values }) => ({
        setFunnel: ({ update }) => {
            if (update) actions.updateFunnel(values.funnel)
        },
        loadFunnelSuccess: ({ funnel }) => {
            if (values.stepsWithCount[0]?.people.length > 0) {
                actions.loadPeople(values.stepsWithCount)
            }
            actions.setAllFilters({
                funnelId: funnel.id,
                name: funnel.name,
                date_from: funnel.filters.date_from,
                date_to: funnel.filters.date_to,
            })
        },
        updateFunnelSuccess: async ({ funnel }) => {
            if (values.stepsWithCount[0]?.people.length > 0) {
                actions.loadPeople(values.stepsWithCount)
            }
            actions.setAllFilters({
                funnelId: funnel.id,
                name: funnel.name,
                date_from: funnel.filters.date_from,
                date_to: funnel.filters.date_to,
            })
            toast('Funnel saved!')
        },
        createFunnelSuccess: ({ funnel }) => {
            if (values.stepsWithCount[0]?.people.length > 0) {
                actions.loadPeople(values.stepsWithCount)
            }
            actions.setAllFilters({
                funnelId: funnel.id,
                name: funnel.name,
                date_from: funnel.filters.date_from,
                date_to: funnel.filters.date_to,
            })
            toast('Funnel saved!')
        },
    }),
    actionToUrl: ({ actions }) => ({
        [actions.createFunnelSuccess]: ({ funnel }) => {
            return ['/insights', { id: funnel.id, insight: ViewType.FUNNELS }]
        },
        [actions.clearFunnel]: () => {
            return ['/insights', { insight: ViewType.FUNNELS }]
        },
    }),

    urlToAction: ({ actions, values }) => ({
        '/insights': (_, searchParams) => {
            if (searchParams.insight === ViewType.FUNNELS) {
                const id = searchParams.id
                if (id != values.funnel.id) {
                    actions.loadFunnel(id)
                }

                const paramsToCheck = {
                    date_from: searchParams.date_from,
                    date_to: searchParams.date_to,
                }

                const _filters = {
                    date_from: values.funnel.filters.date_from,
                    date_to: values.funnel.filters.date_to,
                }

                if (!objectsEqual(_filters, paramsToCheck) && values.funnel.id) {
                    actions.setFunnel({ filters: paramsToCheck }, true)
                }
            }
        },
    }),
    events: ({ actions, key }) => ({
        afterMount: () => {
            if (key === 'new') {
                return
            }

            actions.loadFunnel()
        },
    }),
})
