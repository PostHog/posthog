import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

export const dashboardWidgetsFeaturePreviewUrl = (): string =>
    combineUrl(urls.settings('user-feature-previews'), {}, FEATURE_FLAGS.DASHBOARD_WIDGETS).url
