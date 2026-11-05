import { PAGE_AGENT_REQUEST_SOURCE, PageAgentRequest } from './messaging/pageAgentProtocol'

const userOverrides = { 'other-flag': 'test' }
const userPayloads = { 'other-flag': { color: 'blue' } }
const comparedOverrides = { ...userOverrides, 'new-checkout': true }

let persisted: Record<string, unknown>
let nextId = 1

function sendToPageAgent(request: PageAgentRequest): void {
    window.dispatchEvent(
        new MessageEvent('message', {
            data: { source: PAGE_AGENT_REQUEST_SOURCE, id: nextId++, request },
            source: window,
        })
    )
}

describe('pageAgent', () => {
    beforeAll(() => {
        jest.spyOn(window, 'postMessage').mockImplementation(() => undefined)
        ;(window as unknown as { posthog: unknown }).posthog = {
            __loaded: true,
            get_property: (key: string) => persisted[key],
            featureFlags: {
                overrideFeatureFlags: (options: false | { flags?: unknown; payloads?: unknown }) => {
                    if (options === false) {
                        persisted = {}
                        return
                    }
                    if (options.flags !== undefined) {
                        persisted.$override_feature_flags = options.flags
                    }
                    if (options.payloads !== undefined) {
                        persisted.$override_feature_flag_payloads = options.payloads
                    }
                },
            },
        }
        require('./pageAgent')
    })

    afterAll(() => {
        jest.restoreAllMocks()
        delete (window as unknown as { posthog?: unknown }).posthog
    })

    beforeEach(() => {
        persisted = { $override_feature_flags: userOverrides, $override_feature_flag_payloads: userPayloads }
    })

    test.each([
        {
            outcome: 'restores the overrides from before a comparison when the page unloads during it',
            duringComparison: () => {},
            expectedOverrides: userOverrides,
        },
        {
            outcome: 'keeps overrides that a logout cleared during the comparison',
            duringComparison: () => {
                persisted.$override_feature_flags = undefined
            },
            expectedOverrides: undefined,
        },
        {
            outcome: 'leaves the overrides alone once the comparison ended',
            duringComparison: () => sendToPageAgent({ method: 'restore-flags-on-unload', flags: null }),
            expectedOverrides: comparedOverrides,
        },
    ])('$outcome', ({ duringComparison, expectedOverrides }) => {
        sendToPageAgent({ method: 'restore-flags-on-unload', flags: userOverrides })
        sendToPageAgent({ method: 'override-flags', flags: comparedOverrides })
        duringComparison()

        window.dispatchEvent(new Event('pagehide'))

        expect(persisted).toEqual({
            $override_feature_flags: expectedOverrides,
            $override_feature_flag_payloads: userPayloads,
        })
    })
})
