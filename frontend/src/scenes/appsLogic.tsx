import { kea } from 'kea'
import type { appsLogicType } from './appsLogicType'
import { getAppContext } from 'lib/utils/getAppContext'
import React from 'react'
import * as allKea from 'kea'
import { AdHocInsight } from 'scenes/insights/AdHocInsight'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonRow } from 'lib/components/LemonRow'
import { organizationLogic } from 'scenes/organizationLogic'
import { FrontendPlugin } from '~/types'

export const appsLogic = kea<appsLogicType>({
    path: ['scenes', 'appsLogic'],
    actions: {
        loadFrontendPlugin: (id: number) => ({ id }),
    },
    loaders: ({ values }) => ({
        apps: [
            {} as Record<string, FrontendPlugin>,
            {
                loadFrontendPlugin: async ({ id }) => {
                    try {
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
                        if ('getFrontendPluginExports' in exports) {
                            const app = exports.getFrontendPluginExports(require)
                            if ('scene' in app) {
                                return { ...values.apps, [id]: { ...app.scene, id } }
                            }
                            throw Error(`Could not find exported "scene" for plugin ${id}`)
                        }
                        throw Error(`Could not find exported "getFrontendPluginExports" for plugin ${id}`)
                    } catch (error) {
                        console.error(`Can not load frontend for plugin ${id}`)
                        console.error(error)
                        throw error
                    }
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            const appContext = getAppContext()
            for (const id of appContext?.frontend_apps || []) {
                actions.loadFrontendPlugin(id)
            }
        },
    }),
})
