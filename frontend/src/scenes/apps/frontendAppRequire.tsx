import React from 'react'
import * as allKea from 'kea'
import { AdHocInsight } from 'scenes/insights/AdHocInsight'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonRow } from 'lib/components/LemonRow'

/** Every `import` in a frontend app will be piped through here */
export function frontendAppRequire(module: string): any {
    if (module === 'react') {
        return React
    } else if (module === 'kea') {
        return allKea
    } else if (module === '@posthog/apps-common') {
        return { AdHocInsight: AdHocInsight, LemonButton: LemonButton, LemonRow: LemonRow }
    } else {
        throw new Error(`Can not import from unknown module "${module}"`)
    }
}
