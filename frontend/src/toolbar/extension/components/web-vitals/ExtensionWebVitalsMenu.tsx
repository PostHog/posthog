import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'

import { urls } from '~/toolbar/shared/urls'
import { WebVitalsReport } from '~/toolbar/shared/web-vitals/WebVitalsReport'

import { extensionPageToolbarConnectionLogic } from '../../logics/panel/extensionPageToolbarConnectionLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'
import { ExtensionToolLoading } from '../panel/ExtensionToolLoading'

const WEB_VITALS_DOCS_URL = 'https://posthog.com/docs/web-analytics/web-vitals'

export function ExtensionWebVitalsMenu(): JSX.Element {
    const { webVitals } = useValues(extensionPageToolbarConnectionLogic)
    const { sendCommand } = useActions(extensionPageToolbarConnectionLogic)
    const { projectUrl } = useValues(extensionPanelLogic)

    if (!webVitals) {
        return <ExtensionToolLoading />
    }

    return (
        <div className="flex flex-col gap-2">
            <WebVitalsReport
                localWebVitals={webVitals.localWebVitals}
                remoteWebVitals={webVitals.remoteWebVitals}
                pathname={webVitals.pathname}
                autocaptureEnabled={webVitals.autocaptureEnabled}
                settingsUrl={projectUrl(urls.settings())}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-x-3 text-xs">
                    <Link to={projectUrl(urls.webAnalyticsWebVitals())} target="_blank">
                        View all metrics
                    </Link>
                    <Link to={WEB_VITALS_DOCS_URL} target="_blank">
                        Web vitals docs
                    </Link>
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={() => sendCommand({ tool: 'web-vitals', command: { type: 'reload-web-vitals' } })}
                    data-attr="toolbar-extension-web-vitals-reload"
                >
                    Reload
                </LemonButton>
            </div>
        </div>
    )
}
