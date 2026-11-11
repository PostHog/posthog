import { DateTime } from 'luxon'

import { PostgresRouter } from '~/common/utils/db/postgres'

import { CyclotronJobInvocationHogFlow, HogFunctionInvocationGlobals, HogFunctionType } from '../../../types'
import { HogInputsService } from '../../hog-inputs.service'
import { ActionHandlerOptions } from '../../hogflows/actions/action.interface'
import { SandboxEmailAction } from '../../hogflows/actions/email_sandbox'
import { actionIdForLogging } from '../../hogflows/hogflow-utils'
import { AUTHORIZATION_TIMEOUT_MS, readSandboxAuthorization } from './sandbox-authorization'
import { SandboxRenderedEmail, SandboxRenderedEmailSchema } from './sandbox-message'
import { canonicalRecipient } from './sandbox-recipient-checks'

export class SandboxRenderError extends Error {}

export class SandboxRecipientUnavailableError extends Error {}

export type DeliveredAddressReader = (teamId: number, recipient: string) => Promise<string>

export function deliveredAddressReader(
    db: PostgresRouter,
    timeoutMs: number = AUTHORIZATION_TIMEOUT_MS
): DeliveredAddressReader {
    return async (teamId, recipient) => {
        const authorization = await readSandboxAuthorization(db, { teamId, recipient, tenantName: '', timeoutMs })
        if (authorization.ok) {
            return authorization.storedAddress
        }
        if (authorization.reason === 'authorization_unavailable') {
            throw new SandboxRecipientUnavailableError('Could not read the address the sandbox email is delivered to')
        }
        return canonicalRecipient(recipient)
    }
}

export async function renderSandboxEmail(
    hogInputsService: Pick<HogInputsService, 'buildInputsWithGlobals'>,
    invocation: CyclotronJobInvocationHogFlow,
    action: SandboxEmailAction,
    siteUrl: string,
    deliveredAddress: DeliveredAddressReader
): Promise<SandboxRenderedEmail> {
    const { hogFlow } = invocation
    const globals = await hogInputsService.buildInputsWithGlobals(
        sandboxEmailFunction(invocation, action),
        workflowGlobals(invocation, action, siteUrl),
        undefined,
        {
            appSourceId: invocation.parentRunId ?? hogFlow.id,
            instanceId: action.id,
            workflowId: hogFlow.id,
            invocationId: invocation.id,
            workflowVersion: hogFlow.version,
        },
        undefined,
        { recipientIdentifier: (email) => deliveredAddress(invocation.teamId, email) }
    )
    const parsed = SandboxRenderedEmailSchema.safeParse(globals.inputs.email)
    if (!parsed.success) {
        throw new SandboxRenderError('The rendered sandbox email is missing a recipient, subject, or content')
    }
    return parsed.data
}

export function logRenderFailure({ action, result }: ActionHandlerOptions<SandboxEmailAction>, error: unknown): void {
    result.logs.push({
        level: 'error',
        timestamp: DateTime.now(),
        message: `${actionIdForLogging(action)} Sandbox email failed to render: ${error instanceof Error ? error.message : String(error)}`,
    })
}

function sandboxEmailFunction(invocation: CyclotronJobInvocationHogFlow, action: SandboxEmailAction): HogFunctionType {
    return {
        id: invocation.hogFlow.id,
        team_id: invocation.hogFlow.team_id,
        name: `${invocation.hogFlow.name} - ${action.name}`,
        type: 'destination',
        enabled: true,
        deleted: false,
        hog: '',
        bytecode: [],
        inputs_schema: [{ key: 'email', type: 'native_email', templating: true }],
        inputs: action.config.inputs,
        created_at: '',
        updated_at: '',
    }
}

function workflowGlobals(
    invocation: CyclotronJobInvocationHogFlow,
    action: SandboxEmailAction,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const { hogFlow } = invocation
    return {
        event: invocation.state.event,
        person: invocation.person,
        groups: invocation.groups,
        variables: invocation.state.variables,
        source: {
            id: hogFlow.id,
            name: hogFlow.name || `Hog flow: ${hogFlow.id}`,
            url: `${siteUrl}/project/${hogFlow.team_id}/workflows/${hogFlow.id}/workflow?node=${action.id}`,
        },
        project: { id: hogFlow.team_id, name: '', url: '' },
    }
}
