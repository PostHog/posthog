import { afterMount, beforeUnmount, connect, kea, path } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { webMcpLogicType } from './webMcpLogicType'
import { buildWebMcpTools } from './webMcpToolkit'
import type { WebMcpToolRegistration } from './webMcpTypes'

export const webMcpLogic = kea<webMcpLogicType>([
    path(['lib', 'components', 'WebMcp', 'webMcpLogic']),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    afterMount(({ values, cache }) => {
        if (!values.featureFlags[FEATURE_FLAGS.WEB_MCP]) {
            return
        }
        if (!navigator.modelContext) {
            return
        }

        const tools = buildWebMcpTools()
        const registrations: WebMcpToolRegistration[] = []

        for (const tool of tools) {
            registrations.push(navigator.modelContext.registerTool(tool))
        }

        cache.registrations = registrations
    }),

    beforeUnmount(({ cache }) => {
        const registrations = cache.registrations as WebMcpToolRegistration[] | undefined
        if (registrations) {
            for (const reg of registrations) {
                reg.unregister()
            }
            cache.registrations = undefined
        }
    }),
])
