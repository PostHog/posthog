import { ComponentType } from 'react'

import { GenericIssueRenderer } from './renderers/GenericIssueRenderer'
import { SdkOutdatedRenderer } from './renderers/SdkOutdatedRenderer'
import type { HealthIssue } from './types'

const HEALTH_ISSUE_RENDERERS: Record<string, ComponentType<{ issue: HealthIssue }>> = {
    sdk_outdated: SdkOutdatedRenderer,
}

export const getIssueRenderer = (kind: string): ComponentType<{ issue: HealthIssue }> => {
    return HEALTH_ISSUE_RENDERERS[kind] ?? GenericIssueRenderer
}
