import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { announcementLogic, DEFAULT_CLOUD_ANNOUNCEMENT } from './announcementLogic'

describe('announcementLogic', () => {
    let logic: ReturnType<typeof announcementLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = announcementLogic()
        logic.mount()
        await expectLogic(logic).toMount([featureFlagLogic])
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.CLOUD_ANNOUNCEMENT], {
            [FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]: true,
        })
    })

    afterEach(() => logic.unmount())
    it('shows a cloud announcement', async () => {
        await expectLogic(logic).toMatchValues({
            cloudAnnouncement: DEFAULT_CLOUD_ANNOUNCEMENT,
            showAnnouncement: true,
        })
    })

    it('hides announcements during the ingestion phase', async () => {
        router.actions.push(urls.products())
        await expectLogic(logic).toMatchValues({
            cloudAnnouncement: DEFAULT_CLOUD_ANNOUNCEMENT,
            showAnnouncement: false,
        })
    })
})
