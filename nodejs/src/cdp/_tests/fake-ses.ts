import { SesMessage, startProviderEdge } from '~/tests/scenarios/provider-edge'

export type FakeSesMessage = SesMessage

export type FakeSesFault = { status: number; type: string; message: string } | 'drop-connection'

export interface FakeSes {
    endpoint: string
    readonly sent: FakeSesMessage[]
    failWith(fault: FakeSesFault): void
    close(): Promise<void>
}

type ConfigurationSets = Record<string, { tracking: boolean }>

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
            return edge.records.flatMap((record) => (record.detail.message ? [record.detail.message] : []))
        },
        // A fault answers every later send, because the SDK retries throttles, 5xx responses and dropped
        // connections on its own before the caller sees an error.
        failWith: (fault) => {
            edge.clearFaults()
            edge.addFault(
                fault === 'drop-connection'
                    ? { name: 'ses.drop_connection', answer: { kind: 'drop-connection' }, dose: { share: 1 } }
                    : { name: 'ses.status', answer: { kind: 'status', answer: fault }, dose: { share: 1 } }
            )
        },
        close: async () => {
            setVariables(previousCredentials)
            await edge.close()
        },
    }
}
