import { useValues } from 'kea'
import { router } from 'kea-router'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
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
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)

    if (projectCreationForbiddenReason) {
        return (
            <LemonBanner type="warning" className="mt-5">
                {projectCreationForbiddenReason}
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
            {/* Give the inline scene a working exit (Cancel + close) so a failed create doesn't trap the user. */}
            <CreateProjectModal isVisible inline onClose={() => router.actions.push(urls.projectHomepage())} />
        </PayGateMini>
    )
}
