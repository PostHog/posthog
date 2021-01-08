import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { appEditorUrl } from 'lib/components/AppEditorLink/utils'
import { toast } from 'react-toastify'
import { userLogic } from 'scenes/userLogic'
import moment from 'moment'

const defaultValue = 'https://'

export const appUrlsLogic = kea({
    actions: () => ({
        addUrl: (value) => ({ value }),
        addUrlAndGo: (value) => ({ value }),
        removeUrl: (index) => ({ index }),
        updateUrl: (index, value) => ({ index, value }),
    }),

    loaders: ({ values }) => ({
        suggestions: {
            __default: [],
            loadSuggestions: async () => {
                let params = {
                    events: [{ id: '$pageview', name: '$pageview', type: 'events' }],
                    breakdown: '$current_url',
                    date_from: moment().subtract(3, 'days').toISOString(),
                }
                let data = await api.get('api/insight/trend/?' + toParams(params))
                if (data[0]?.count === 0) {
                    return []
                }
                let domainsSeen = []
                return data
                    .filter((item) => {
                        try {
                            let domain = new URL(item.breakdown_value).hostname
                            if (domainsSeen.indexOf(domain) > -1) {
                                return
                            }
                            if (values.appUrls.filter((url) => url.indexOf(domain) > -1).length > 0) {
                                return
                            }
                            domainsSeen.push(domain)
                            return true
                        } catch (error) {
                            return false
                        }
                    })
                    .map((item) => item.breakdown_value)
                    .slice(0, 20)
            },
        },
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadSuggestions,
    }),

    defaults: () => ({
        appUrls: (state) => userLogic.selectors.user(state).team.app_urls || [defaultValue],
    }),

    allURLs: ({ selectors }) => ({
        recordsForSelectedMonth: [
            () => [selectors.appUrls, selectors.suggestions],
            (appUrls, suggestions) => {
                return appUrls + suggestions
            },
        ],
    }),

    reducers: ({ actions }) => ({
        appUrls: [
            [defaultValue],
            {
                [actions.addUrl]: (state, { value }) => state.concat([value || defaultValue]),
                [actions.updateUrl]: (state, { index, value }) => Object.assign([...state], { [index]: value }),
                [actions.removeUrl]: (state, { index }) => {
                    const newAppUrls = [...state]
                    newAppUrls.splice(index, 1)
                    return newAppUrls
                },
            },
        ],
        suggestions: [
            [],
            {
                [actions.addUrl]: (state, { value }) => [...state].filter((item) => value !== item),
            },
        ],
    }),

    listeners: ({ values, sharedListeners, props }) => ({
        addUrlAndGo: async ({ value }) => {
            let app_urls = [...values.appUrls, value]
            await api.update('api/user', { team: { app_urls } })
            window.location.href = appEditorUrl(props.actionId, value)
        },
        removeUrl: sharedListeners.saveAppUrls,
        updateUrl: sharedListeners.saveAppUrls,
    }),

    sharedListeners: ({ values }) => ({
        saveAppUrls: ({ value }) => {
            // Only show toast when clicking "Save"
            if (value) {
                toast('URLs saved', { toastId: 'EditAppUrls' })
            }
            userLogic.actions.userUpdateRequest({ team: { app_urls: values.appUrls } }, 'SetupAppUrls')
        },
    }),
})
