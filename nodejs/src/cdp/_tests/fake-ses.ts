import { FaultRule, SesAttachment, SesMessage, startProviderEdge } from '~/tests/scenarios/provider-edge'

export type FakeSesAttachment = SesAttachment

export type FakeSesMessage = SesMessage

export type FakeSesFault =
    | { status: number; type: string; message: string }
    | { acceptedThen: { status: number; type: string; message: string } }
    | 'drop-connection'
    | 'accept-then-drop-connection'
    | 'answer-without-message-id'
    | 'no-answer'
    | 'stalled-body'

export interface FakeSes {
    endpoint: string
    readonly sent: FakeSesMessage[]
    failWith(fault: FakeSesFault | null): void
    failInTurn(...faults: FakeSesFault[]): void
    failOnce(fault: FakeSesFault): void
    close(): Promise<void>
}

type ConfigurationSets = Record<string, { tracking: boolean }>

function faultRuleOf(fault: FakeSesFault, dose: FaultRule['dose'] = { share: 1 }): FaultRule {
    if (typeof fault === 'object' && 'acceptedThen' in fault) {
        return {
            name: 'ses.accepted_then_status',
            answer: { kind: 'accepted-then-status', answer: fault.acceptedThen },
            dose,
        }
    }
    switch (fault) {
        case 'drop-connection':
            return { name: 'ses.drop_connection', answer: { kind: 'drop-connection' }, dose }
        case 'accept-then-drop-connection':
            return { name: 'ses.accept_then_drop', answer: { kind: 'ambiguous', accepted: true }, dose }
        case 'answer-without-message-id':
            return {
                name: 'ses.no_message_id',
                answer: { kind: 'accepted-then-status', answer: { status: 200, type: '', message: '' } },
                dose,
            }
        case 'no-answer':
            return { name: 'ses.no_answer', answer: { kind: 'no-answer' }, dose }
        case 'stalled-body':
            return { name: 'ses.stalled_body', answer: { kind: 'stalled-body' }, dose }
        default:
            return { name: 'ses.status', answer: { kind: 'status', answer: fault }, dose }
    }
}

export async function startFakeSes(configurationSets: ConfigurationSets): Promise<FakeSes> {
    const edge = await startProviderEdge({ port: 0, configurationSets })

    // The SDK signs every request, so it needs credentials even though the fake accepts any. It ignores
    // the key pair while AWS_PROFILE is set, so the profile is unset until the fake closes.
    const credentialVariables = {
        AWS_ACCESS_KEY_ID: 'fake-ses',
        AWS_SECRET_ACCESS_KEY: 'fake-ses',
        AWS_PROFILE: undefined,
    }
    const setVariables = (values: Record<string, string | undefined>): void =>
        Object.entries(values).forEach(([name, value]) => {
            if (value === undefined) {
                delete process.env[name]
            } else {
                process.env[name] = value
            }
        })
    const previousCredentials = Object.fromEntries(
        Object.keys(credentialVariables).map((name) => [name, process.env[name]])
    )
    setVariables(credentialVariables)

    return {
        endpoint: edge.url,
        get sent() {
            return [...edge.sent]
        },
        // A fault answers every later send, because the SDK retries throttles, 5xx responses and dropped
        // connections on its own before the caller sees an error.
        failWith: (fault) => {
            edge.clearFaults()
            if (fault) {
                edge.addFault(faultRuleOf(fault))
            }
        },
        failInTurn: (...faults) => {
            edge.clearFaults()
            faults.forEach((fault, turn) =>
                edge.addFault(faultRuleOf(fault, turn < faults.length - 1 ? { count: 1 } : { share: 1 }))
            )
        },
        failOnce: (fault) => {
            edge.clearFaults()
            edge.addFault(faultRuleOf(fault, { count: 1 }))
        },
        close: async () => {
            setVariables(previousCredentials)
            await edge.close()
        },
    }
}
