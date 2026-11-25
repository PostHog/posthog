import { isHostedCloud, isHostedCloudDeployment } from './env-utils'

describe('isHostedCloud', () => {
    const originalCloudDeployment = process.env.CLOUD_DEPLOYMENT

    afterEach(() => {
        if (originalCloudDeployment === undefined) {
            delete process.env.CLOUD_DEPLOYMENT
        } else {
            process.env.CLOUD_DEPLOYMENT = originalCloudDeployment
        }
    })

    it.each<{ cloudDeployment: string | null; expected: boolean }>([
        { cloudDeployment: 'US', expected: true },
        { cloudDeployment: 'EU', expected: true },
        { cloudDeployment: 'DEV', expected: true },
        { cloudDeployment: 'us', expected: true },
        { cloudDeployment: 'E2E', expected: false },
        { cloudDeployment: 'HOSTHOG_PROD_US', expected: false },
        { cloudDeployment: '', expected: false },
        { cloudDeployment: null, expected: false },
    ])('isHostedCloudDeployment($cloudDeployment) is $expected', ({ cloudDeployment, expected }) => {
        expect(isHostedCloudDeployment(cloudDeployment)).toBe(expected)
    })

    it.each<{ env: string | undefined; expected: boolean }>([
        { env: 'EU', expected: true },
        { env: 'E2E', expected: false },
        { env: undefined, expected: false },
    ])('isHostedCloud() reads CLOUD_DEPLOYMENT=$env', ({ env, expected }) => {
        if (env === undefined) {
            delete process.env.CLOUD_DEPLOYMENT
        } else {
            process.env.CLOUD_DEPLOYMENT = env
        }
        expect(isHostedCloud()).toBe(expected)
    })
})
