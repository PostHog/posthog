import '~/styles'
import React from 'react'
import { mount } from '@cypress/react'
import { Provider } from 'react-redux'
import { getContext, useValues } from 'kea'
import { initKea } from '~/initKea'
import { userLogic } from 'scenes/userLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import posthog from 'posthog-js'
import { toParams } from '~/lib/utils'

export const mountPage = (component) => {
    initKea()
    return mount(
        <Provider store={getContext().store}>
            <WaitUntilEssentialLogicsAreMounted>{component}</WaitUntilEssentialLogicsAreMounted>
        </Provider>
    )
}

function WaitUntilEssentialLogicsAreMounted({ children }) {
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)

    return user && preflight ? children : null
}

export const setLocation = (path, params = null) => {
    let qs = ''
    if (params) {
        qs = '?' + toParams(params)
    }
    window.history.replaceState(null, '', path + qs)
}

export const getSearchParameters = ({ request }) => {
    const searchParams = new URL(request.url).searchParams
    const result = {}
    for (const [key, value] of searchParams.entries()) {
        result[key] = value
    }
    return result
}

export const mockPosthog = () => {
    cy.stub(posthog)
    posthog.people = { set: () => {} }
    posthog.onFeatureFlags = (callback) => {
        if (Array.isArray(given.featureFlags)) {
            callback(given.featureFlags, Object.fromEntries(given.featureFlags.map((f) => [f, true])))
        } else if (typeof given.featureFlags === 'object') {
            callback(Object.keys(given.featureFlags), given.featureFlags)
        } else {
            callback([], {})
        }
    }
}
