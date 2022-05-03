import { kea } from 'kea'
import type { appsLogicType } from './appsLogicType'
import { getAppContext } from 'lib/utils/getAppContext'
import React from 'react'
import * as allKea from 'kea'
import { AdHocInsight } from 'scenes/insights/AdHocInsight'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonRow } from 'lib/components/LemonRow'
import { organizationLogic } from 'scenes/organizationLogic'

export const appsLogic = kea<appsLogicType>({
    path: ['scenes', 'appsLogic'],
    actions: {
        loadApp: (id: number) => ({ id }),
    },
    loaders: ({ values }) => ({
        apps: [
            {} as Record<string, any>,
            {
                loadApp: async ({ id }) => {
                    try {
                        // @ts-ignore
                        // eslint-disable-next-line
                        const require = (module: string): any => {
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
                        const siteUrl = `http://localhost:8000`
                        const exports = await import(
                            `${siteUrl}/api/organizations/${organizationLogic.values.currentOrganization?.id}/plugins/${id}/frontend`
                        )
                        console.log({ exports })
                        const app = exports.getFrontendPluginExports(require)
                        // debugger
                        return { ...values.apps, [id]: app }
                    } catch (error) {
                        console.error(`Can not load frontend for plugin ${id}`)
                        console.error(error)
                    }
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            const appContext = getAppContext()
            for (const id of appContext?.frontend_apps || []) {
                actions.loadApp(id)
            }
        },
    }),
})

//
//             }
//         }
//         for (const plugin of values.frontendPlugins) {
//             if (!enabledFrontendPlugins.find((p) => p.id === plugin.id)) {
//                 actions.stopFrontendPlugin(plugin)
//             }
//         }
//     },
// }),
