import './style.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import App from './scenes/App'
import { initKea } from './initKea'
import posthog from 'posthog-js'
import * as Sentry from '@sentry/browser'

posthog.init('sTMFPsFhdP1Ssg')

if ((window as any).SENTRY_DSN) {
    Sentry.init({
        dsn: (window as any).SENTRY_DSN,
        integrations: [new posthog.SentryIntegration(posthog, 'posthog', 1899813)],
    })
}

initKea()

ReactDOM.render(
    <Provider store={getContext().store}>
        <App />
    </Provider>,
    document.getElementById('root')
)
