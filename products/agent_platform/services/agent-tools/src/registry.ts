/**
 * Native tool registry. Two methods land everything the runner and authoring
 * layer need:
 *   - get(id)   — runner lookup; throws if unknown.
 *   - list()    — authoring catalog (description, args schema, requires).
 *
 * Tools are statically registered at module load. To add a tool: create the
 * file, import its default export here, push into ALL_TOOLS. Tests live next
 * to the tool. No magic discovery.
 */

import { defineNativeTool, NativeTool, NativeToolSchema, Type } from '@posthog/agent-shared'

import { httpRequestV1 } from './tools/http-request.v1'
import { identityConnectV1 } from './tools/identity-connect.v1'
import { identityFetchV1 } from './tools/identity-fetch.v1'
import { loadSkill } from './tools/load-skill'
import {
    memoryDeleteV1,
    memoryListV1,
    memoryReadV1,
    memorySearchV1,
    memoryUpdateV1,
    memoryWriteV1,
} from './tools/memory'
import { endSessionTool, endTurnTool, emitEventTool } from './tools/meta'
import {
    posthogAgentApplicationsCreateV1,
    posthogAgentApplicationsEnvKeysGetV1,
    posthogAgentApplicationsEnvKeysListV1,
    posthogAgentApplicationsListV1,
    posthogAgentApplicationsPartialUpdateV1,
    posthogAgentApplicationsRetrieveV1,
    posthogAgentApplicationsRevisionsArchiveV1,
    posthogAgentApplicationsRevisionsCreateV1,
    posthogAgentApplicationsRevisionsAgentMdUpdateV1,
    posthogAgentApplicationsRevisionsBundleRetrieveV1,
    posthogAgentApplicationsRevisionsFreezeV1,
    posthogAgentApplicationsRevisionsListV1,
    posthogAgentApplicationsRevisionsManifestV1,
    posthogAgentApplicationsRevisionsNewDraftV1,
    posthogAgentApplicationsRevisionsPartialUpdateV1,
    posthogAgentApplicationsRevisionsPromoteV1,
    posthogAgentApplicationsRevisionsRetrieveV1,
    posthogAgentApplicationsRevisionsSkillRefsSetV1,
    posthogAgentApplicationsRevisionsSlackManifestV1,
    posthogAgentApplicationsRevisionsSystemPromptV1,
    posthogAgentApplicationsRevisionsToolsDestroyV1,
    posthogAgentApplicationsRevisionsToolsUpdateV1,
    posthogAgentApplicationsRevisionsValidateV1,
    posthogAgentApplicationsSessionLogsV1,
    posthogAgentApplicationsSessionsListV1,
    posthogAgentApplicationsSessionsRetrieveV1,
    posthogAgentApplicationsSetEnvV1,
    posthogLlmSkillsCreateV1,
    posthogLlmSkillsSearchV1,
} from './tools/posthog-agent-management.v1'
import { posthogListProjectsV1 } from './tools/posthog-projects.v1'
import { posthogQueryV1 } from './tools/posthog-query.v1'
import {
    slackPostMessageV1,
    slackReactV1,
    slackReadChannelV1,
    slackReadThreadV1,
    slackUpdateMessageV1,
} from './tools/slack.v1'
import {
    tableAppendV1,
    tableCountV1,
    tableDeleteV1,
    tableMembershipV1,
    tableQueryV1,
    tableTruncateV1,
} from './tools/table'
import { webSearchV1 } from './tools/web-search/web-search.v1'

/**
 * Lists every native (`@posthog/*`) tool the runner knows — the authoring
 * concierge's ground-truth catalog of what it can wire into an agent's
 * `tools[]`, instead of guessing tool ids from its (drift-prone) skill docs.
 * Defined here rather than in `tools/` so it can read `listNativeTools()`
 * without a registry↔tool import cycle; `run` reads the catalog at call time.
 */
export const nativeToolsCatalogV1 = defineNativeTool({
    id: '@posthog/agent-applications-native-tools-list',
    approval: 'allow',
    description: [
        'List every native (@posthog/*) tool available to put in an agent spec —',
        'id, description, the credential provider + scopes it needs, and cost hint. Call this to',
        'discover what tools you can wire into an agent you are building or editing,',
        'instead of guessing tool ids. The validator rejects unknown ids, so check here first.',
    ].join(' '),
    args: Type.Object({}),
    returns: Type.Object({
        tools: Type.Array(
            Type.Object({
                id: Type.String(),
                description: Type.String(),
                requires: Type.Object({
                    provider: Type.Optional(Type.Object({ id: Type.String(), scopes: Type.Array(Type.String()) })),
                }),
                cost_hint: Type.String(),
            })
        ),
    }),
    cost_hint: 'cheap',
    async run() {
        return {
            tools: listNativeTools().map((t) => ({
                id: t.id,
                description: t.schema.description,
                requires: { provider: t.schema.requires.provider },
                cost_hint: t.schema.cost_hint,
            })),
        }
    },
})

export const ALL_TOOLS: NativeTool[] = [
    posthogQueryV1,
    posthogListProjectsV1,
    posthogAgentApplicationsListV1,
    posthogAgentApplicationsRetrieveV1,
    posthogAgentApplicationsRevisionsListV1,
    posthogAgentApplicationsRevisionsRetrieveV1,
    posthogAgentApplicationsRevisionsSystemPromptV1,
    posthogAgentApplicationsRevisionsManifestV1,
    posthogAgentApplicationsRevisionsBundleRetrieveV1,
    posthogAgentApplicationsRevisionsSlackManifestV1,
    posthogAgentApplicationsCreateV1,
    posthogAgentApplicationsPartialUpdateV1,
    posthogAgentApplicationsRevisionsCreateV1,
    posthogAgentApplicationsRevisionsNewDraftV1,
    posthogAgentApplicationsRevisionsPartialUpdateV1,
    posthogAgentApplicationsRevisionsAgentMdUpdateV1,
    posthogLlmSkillsSearchV1,
    posthogLlmSkillsCreateV1,
    posthogAgentApplicationsRevisionsSkillRefsSetV1,
    posthogAgentApplicationsRevisionsToolsUpdateV1,
    posthogAgentApplicationsRevisionsToolsDestroyV1,
    posthogAgentApplicationsRevisionsValidateV1,
    posthogAgentApplicationsRevisionsFreezeV1,
    posthogAgentApplicationsRevisionsPromoteV1,
    posthogAgentApplicationsRevisionsArchiveV1,
    posthogAgentApplicationsEnvKeysListV1,
    posthogAgentApplicationsEnvKeysGetV1,
    posthogAgentApplicationsSetEnvV1,
    posthogAgentApplicationsSessionsListV1,
    posthogAgentApplicationsSessionsRetrieveV1,
    posthogAgentApplicationsSessionLogsV1,
    nativeToolsCatalogV1,
    slackPostMessageV1,
    slackUpdateMessageV1,
    slackReadChannelV1,
    slackReadThreadV1,
    slackReactV1,
    httpRequestV1,
    identityConnectV1,
    identityFetchV1,
    webSearchV1,
    endTurnTool,
    endSessionTool,
    emitEventTool,
    loadSkill,
    memoryListV1,
    memorySearchV1,
    memoryReadV1,
    memoryWriteV1,
    memoryUpdateV1,
    memoryDeleteV1,
    tableMembershipV1,
    tableAppendV1,
    tableQueryV1,
    tableCountV1,
    tableDeleteV1,
    tableTruncateV1,
]

const BY_ID = new Map<string, NativeTool>(ALL_TOOLS.map((t) => [t.id, t]))

export function getNativeTool(id: string): NativeTool {
    const t = BY_ID.get(id)
    if (!t) {
        throw new Error(`unknown native tool: ${id}`)
    }
    return t
}

export function hasNativeTool(id: string): boolean {
    return BY_ID.has(id)
}

export interface NativeToolCatalogEntry {
    id: string
    schema: NativeToolSchema
}

/** Catalog view for the authoring MCP. Strips the run() function. */
export function listNativeTools(): NativeToolCatalogEntry[] {
    return ALL_TOOLS.map((t) => ({ id: t.id, schema: t.schema }))
}
