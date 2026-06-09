import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

export const dashboardWidgetsFeaturePreviewUrl = (): string =>
    urls.settings('user-feature-previews', FEATURE_FLAGS.DASHBOARD_WIDGETS)
