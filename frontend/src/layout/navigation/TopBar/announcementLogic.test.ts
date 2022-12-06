import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { billingLogic } from '~/scenes/billing/billingLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { announcementLogic, AnnouncementType } from './announcementLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from '../navigationLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const MOCK_CLOUD_ANNOUNCEMENT = 'This is a cloud announcement'

describe('announcementLogic', () => {
    let logic: ReturnType<typeof announcementLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = announcementLogic()
        logic.mount()
        await expectLogic(logic).toMount([featureFlagLogic, preflightLogic, userLogic, navigationLogic, billingLogic])
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.CLOUD_ANNOUNCEMENT], {
            [FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]: MOCK_CLOUD_ANNOUNCEMENT,
        })
    })

    afterEach(() => logic.unmount())
    it('shows a cloud announcement', async () => {
        await expectLogic(logic).toMatchValues({
            cloudAnnouncement: MOCK_CLOUD_ANNOUNCEMENT,
            shownAnnouncementType: AnnouncementType.CloudFlag,
        })
    })

    it('hides announcements during the ingestion phase', async () => {
        router.actions.push(urls.ingestion())
        await expectLogic(logic).toMatchValues({
            cloudAnnouncement: MOCK_CLOUD_ANNOUNCEMENT,
            shownAnnouncementType: null,
        })
    })
})
