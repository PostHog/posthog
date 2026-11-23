import { hogql, insight } from '@posthog/sdk/define'

export const shared = insight('shared', hogql({ name: 'Shared', query: 'select 1' }))
