import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { ToolbarMenu } from '~/toolbar/floating/components/bar/ToolbarMenu'
import { urls } from '~/toolbar/shared/urls'

import { toolbarAppUrl, toolbarConfigLogic } from '../../../shared/toolbarConfigLogic'
import { WebVitalsReport } from '../../../shared/web-vitals/WebVitalsReport'
import { webVitalsToolbarLogic } from '../../../shared/web-vitals/webVitalsToolbarLogic'

export const WebVitalsToolbarMenu = (): JSX.Element => {
    const { localWebVitals, remoteWebVitals } = useValues(webVitalsToolbarLogic)
    const { posthog } = useValues(toolbarConfigLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Body>
                <WebVitalsReport
                    localWebVitals={localWebVitals}
                    remoteWebVitals={remoteWebVitals}
                    pathname={window.location.pathname}
                    autocaptureEnabled={!!posthog?.webVitalsAutocapture?.isEnabled}
                    settingsUrl={toolbarAppUrl(urls.settings())}
                />
            </ToolbarMenu.Body>

            <ToolbarMenu.Footer>
                <div className="flex flex-row justify-between w-full">
                    <Link to={toolbarAppUrl(urls.webAnalyticsWebVitals())} target="_blank">
                        View all metrics
                    </Link>
                    <Link to="https://posthog.com/docs/web-analytics/web-vitals" target="_blank">
                        View web vitals docs
                    </Link>
                </div>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
