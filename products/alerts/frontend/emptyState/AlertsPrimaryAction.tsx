import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { AccessControlResourceType } from '~/types'

import { hasEffectiveResourceAccess } from '../utils'

/**
 * Create path for the alerts empty state. Insight alerts are created from an insight,
 * not from this scene, so the action sends the user to their insights. A user who
 * cannot read insights gets no button: their only alert kind is log alerts, which the
 * scene creates behind the setup screen.
 */
export function AlertsPrimaryAction(): JSX.Element | null {
    if (!hasEffectiveResourceAccess(AccessControlResourceType.Insight)) {
        return null
    }

    return (
        <LemonButton type="primary" to={urls.insights()} data-attr="alerts-browse-insights">
            Browse your insights
        </LemonButton>
    )
}
