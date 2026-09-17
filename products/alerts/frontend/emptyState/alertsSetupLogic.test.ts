import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import * as appContext from 'lib/utils/getAppContext'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import * as logsApi from 'products/logs/frontend/generated/api'

import * as generatedApi from '../generated/api'
import { alertsSetupLogic } from './alertsSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('alertsSetupLogic', () => {
    let insightAlertsSpy: jest.SpyInstance
    let logAlertsSpy: jest.SpyInstance

    beforeEach(() => {
        insightAlertsSpy = jest.spyOn(generatedApi, 'alertsList')
        logAlertsSpy = jest.spyOn(logsApi, 'logsAlertsList')
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    async function mountAndReadStatus(): Promise<string> {
        const logic = alertsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        return productSetupStatusLogic({ productKey: ProductKey.ALERTS }).values.status
    }

    it.each([
        ['neither kind exists', 0, 0, 'needs-setup'],
        ['only insight alerts exist', 2, 0, 'has-data'],
        // The scene serves both kinds, so log alerts alone still count as set up.
        ['only log alerts exist', 0, 3, 'has-data'],
    ])('pushes %s as status %s', async (_name, insightAlerts, logAlerts, expected) => {
        insightAlertsSpy.mockResolvedValue({ count: insightAlerts, results: [] })
        logAlertsSpy.mockResolvedValue({ count: logAlerts, results: [] })
        expect(await mountAndReadStatus()).toBe(expected)
    })

    it('skips the kinds the user cannot read', async () => {
        jest.spyOn(appContext, 'getAppContext').mockReturnValue({
            effective_resource_access_control: {
                [AccessControlResourceType.Logs]: AccessControlLevel.None,
            },
        } as ReturnType<typeof appContext.getAppContext>)
        insightAlertsSpy.mockResolvedValue({ count: 0, results: [] })

        expect(await mountAndReadStatus()).toBe('needs-setup')
        expect(logAlertsSpy).not.toHaveBeenCalled()
    })

    it('leaves the scene to its access-denied screen when neither kind is readable', async () => {
        jest.spyOn(appContext, 'getAppContext').mockReturnValue({
            effective_resource_access_control: {
                [AccessControlResourceType.Insight]: AccessControlLevel.None,
                [AccessControlResourceType.Logs]: AccessControlLevel.None,
            },
        } as ReturnType<typeof appContext.getAppContext>)

        expect(await mountAndReadStatus()).toBe('unknown')
        expect(insightAlertsSpy).not.toHaveBeenCalled()
    })

    it('fails open to unknown when a count query fails before any answer', async () => {
        insightAlertsSpy.mockRejectedValue(new Error('network down'))
        logAlertsSpy.mockResolvedValue({ count: 0, results: [] })
        expect(await mountAndReadStatus()).toBe('unknown')
    })
})
