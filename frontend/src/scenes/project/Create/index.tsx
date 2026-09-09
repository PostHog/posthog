import { useValues } from 'kea'
import { router } from 'kea-router'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature } from '~/types'

import { CreateProjectModal } from '../CreateProjectModal'

export const scene: SceneExport = {
    component: ProjectCreate,
    logic: teamLogic,
}

export function ProjectCreate(): JSX.Element {
    const { currentOrganization, projectCreationForbiddenReason, projectCreationUpgradeReason } =
        useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)

    if (projectCreationForbiddenReason) {
        return (
            <LemonBanner type="warning" className="mt-5">
                {projectCreationForbiddenReason}
            </LemonBanner>
        )
    }

    // Give the inline scene a working exit (Cancel + close) so a failed create doesn't trap the user.
    const createForm = (
        <CreateProjectModal isVisible inline onClose={() => router.actions.push(urls.projectHomepage())} />
    )

    // The plan check lives in one selector, so the scene can't paywall a create the backend accepts.
    if (!projectCreationUpgradeReason) {
        return <div className="mt-5">{createForm}</div>
    }

    // PayGateMini shows nothing where paid features are hidden, so state the reason rather than
    // leaving the scene blank.
    if (preflight?.instance_preferences?.disable_paid_fs) {
        return (
            <LemonBanner type="warning" className="mt-5">
                {projectCreationUpgradeReason}
            </LemonBanner>
        )
    }

    return (
        // The paywall replaces the form when the plan has no room for another project, so a submit can't
        // dead-end on the 403 from the create endpoint.
        <PayGateMini
            feature={AvailableFeature.ORGANIZATIONS_PROJECTS}
            currentUsage={currentOrganization?.projects?.length}
            featureDetail="create-project-scene"
            className="mt-5"
        >
            {createForm}
        </PayGateMini>
    )
}
