import React from 'react'
import * as allKea from 'kea'
import * as allKeaRouter from 'kea-router'
import * as allKeaLoaders from 'kea-loaders'
import * as allKeaForms from 'kea-forms'
import * as allKeaWindowValues from 'kea-window-values'
import * as allKeaSubscriptions from 'kea-subscriptions'
import * as appsCommon from '@posthog/apps-common'

const packages = {
    react: React,
    kea: allKea,
    'kea-forms': allKeaForms,
    'kea-loaders': allKeaLoaders,
    'kea-router': allKeaRouter,
    'kea-subscriptions': allKeaSubscriptions,
    'kea-window-values': allKeaWindowValues,
    '@posthog/apps-common': appsCommon,
}

/** Every `import` in a frontend app will be piped through here */
export function frontendAppRequire(module: string): any {
    if (module in packages) {
        return packages[module]
    } else {
        throw new Error(`Cannot import from unknown module "${module}"`)
    }
}
