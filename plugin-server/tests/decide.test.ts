// const API_HOST = process.env.API_HOST || 'http://localhost:8010'
// const API_KEYS_TO_TEST = ['phc_hxPPRO0JZpflkzZNTNBNyoYFD9gRD2vsCuOuoPl5LBx']

import data from './tokens.json'
import process from "node:process";

const API_HOST = process.env.API_HOST || 'https://us.i.posthog.com'
const API_KEYS_TO_TEST = (data as any[])
    .map((token) => token.api_token)
    .filter((x) => x.startsWith('phc_'))
    .slice(0, 1000)

// console.log(API_KEYS_TO_TEST)

describe('decide comparison test', () => {
    it.concurrent.each(API_KEYS_TO_TEST)('should have identical config objects for %s', async (apiKey) => {
        const configResponse = await fetch(`${API_HOST}/array/${apiKey}/config`)

        if (configResponse.status !== 200) {
            console.log(`${API_HOST}/array/${apiKey}/config`)
            return true
        }

        const decideResponse = await fetch(`${API_HOST}/decide?v=3`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                distinct_id: 'test',
                event: 'test',
                properties: {},
                token: apiKey,
            }),
        })

        const decideConfig = await decideResponse.json()
        const configConfig = await configResponse.json()

        // Modify the configs to remove the known differences

        decideConfig.hasFeatureFlags = Object.keys(decideConfig.featureFlags).length > 0

        delete decideConfig.featureFlags
        delete decideConfig.errorsWhileComputingFlags
        delete decideConfig.featureFlagPayloads
        delete decideConfig.config
        delete decideConfig.toolbarParams
        delete decideConfig.isAuthenticated
        delete decideConfig.surveys
        delete decideConfig.defaultIdentifiedOnly

        if (decideConfig.sessionRecording === false) {
            configConfig.sessionRecording = false
        }

        delete configConfig.token
        delete configConfig.surveys
        delete configConfig.defaultIdentifiedOnly

        expect(decideConfig).toEqual(configConfig)
    })
})
