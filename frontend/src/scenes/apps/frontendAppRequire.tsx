import React from 'react'
import * as allKea from 'kea'
import * as appsCommon from 'packages/apps-common'

/** Every `import` in a frontend app will be piped through here */
export function frontendAppRequire(module: string): any {
    if (module === 'react') {
        return React
    } else if (module === 'kea') {
        return allKea
    } else if (module === '@posthog/apps-common') {
        return appsCommon
    } else {
        throw new Error(`Can not import from unknown module "${module}"`)
    }
}
