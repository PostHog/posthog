import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual } from 'lib/utils'
import moment from 'moment'

export const dateOptions = {
    h: 'Hour',
    d: 'Day',
    w: 'Week',
}

export const retentionTableLogic = kea({
    loaders: ({ values }) => ({
        retention: {
            __default: {},
            loadRetention: async () => {
                let params = { properties: values.properties }
                if (values.selectedDate) params['date_from'] = values.selectedDate.toISOString()
                if (values.period) params['period'] = dateOptions[values.period]
                const urlParams = toParams(params)
                return await api.get(`api/action/retention/?${urlParams}`)
            },
        },
    }),
    actions: () => ({
        setProperties: (properties) => ({ properties }),
        dateChanged: (date) => ({ date }),
        setPeriod: (period) => ({ period }),
    }),
    reducers: () => ({
        initialPathname: [(state) => router.selectors.location(state).pathname, { noop: (a) => a }],
        properties: [
            [],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
        selectedDate: [moment().subtract(11, 'days').startOf('day'), { dateChanged: (_, { date }) => date }],
        period: ['d', { setPeriod: (_, { period }) => period }],
    }),
    selectors: ({ selectors }) => ({
        propertiesForUrl: [
            () => [selectors.properties, selectors.selectedDate, selectors.period],
            (properties, selectedDate, period) => {
                let result = {}
                if (Object.keys(properties).length > 0) {
                    result['properties'] = properties
                }
                if (selectedDate) {
                    result['date_from'] = selectedDate.format('YYYY-MM-DD')
                }
                if (selectedDate) {
                    result['period'] = period
                }

                return result
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadRetention,
    }),
    actionToUrl: ({ values }) => ({
        setProperties: () => {
            return [router.values.location.pathname, values.propertiesForUrl]
        },
        dateChanged: () => {
            return [router.values.location.pathname, values.propertiesForUrl]
        },
        setPeriod: () => {
            return [router.values.location.pathname, values.propertiesForUrl]
        },
    }),

    urlToAction: ({ actions, values }) => ({
        '*': (_, searchParams) => {
            try {
                // if the url changed, but we are not anymore on the page we were at when the logic was mounted
                if (router.values.location.pathname !== values.initialPathname) {
                    return
                }
            } catch (error) {
                // since this is a catch-all route, this code might run during or after the logic was unmounted
                // if we have an error accessing the filter value, the logic is gone and we should return
                return
            }

            if (!objectsEqual(searchParams.properties || {}, values.properties)) {
                actions.setProperties(searchParams.properties || {})
            }
            if (!objectsEqual(searchParams.date_from || {}, values.selectedDate.format('YYYY-MM-DD'))) {
                searchParams.date_from && actions.dateChanged(moment(searchParams.date_from))
            }
            if (searchParams.period !== values.period) {
                searchParams.period && actions.setPeriod(searchParams.period)
            }
        },
    }),
    listeners: ({ actions }) => ({
        setProperties: () => actions.loadRetention(),
        dateChanged: () => {
            actions.loadRetention()
        },
        setPeriod: () => {
            actions.loadRetention()
        },
    }),
})
