import { customerioPlugin } from './customerio'
import { intercomPlugin } from './intercom'

export const PLUGINS_BY_ID = {
    [customerioPlugin.id]: customerioPlugin,
    [intercomPlugin.id]: intercomPlugin,
}
