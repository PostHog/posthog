import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Link } from 'lib/lemon-ui/Link'

import { ExtensionDebugInfo } from './ExtensionDebugInfo'
import { ExtensionPiiMasking } from './ExtensionPiiMasking'
import { ExtensionScreenshotForEvent } from './ExtensionScreenshotForEvent'

const TOOLBAR_DOCS_URL = 'https://posthog.com/docs/toolbar?utm_medium=in-product&utm_campaign=toolbar-extension-help'

export function ExtensionMoreMenu(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <ExtensionDebugInfo />
            <LemonDivider className="my-0" />
            <ExtensionPiiMasking />
            <LemonDivider className="my-0" />
            <ExtensionScreenshotForEvent />
            <LemonDivider className="my-0" />
            <Link to={TOOLBAR_DOCS_URL} target="_blank" className="text-xs">
                Toolbar docs
            </Link>
        </div>
    )
}
