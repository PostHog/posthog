import { customerioPlugin } from './customerio'
import { intercomPlugin } from './intercom'
import { posthogFilterOutPlugin } from './posthog-filter-out-plugin'

export const DESTINATION_PLUGINS_BY_ID = {
    [customerioPlugin.id]: customerioPlugin,
    [intercomPlugin.id]: intercomPlugin,
}

export const TRANSFORMATION_PLUGINS_BY_ID = {
    [posthogFilterOutPlugin.id]: posthogFilterOutPlugin,
}
