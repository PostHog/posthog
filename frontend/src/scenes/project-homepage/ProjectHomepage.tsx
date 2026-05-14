import './ProjectHomepage.scss'

import { useValues } from 'kea'

import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'
import { WelcomeDialog } from 'scenes/welcome/WelcomeDialog'
import { wasWelcomeDismissed } from 'scenes/welcome/welcomeDialogLogic'

import { AiFirstHomepage } from './ai-first/AiFirstHomepage'

/** Only mount the welcome dialog (and its kea logic) for users actually eligible to see it. */
function MaybeWelcomeDialog(): JSX.Element | null {
    const { user } = useValues(userLogic)
    if (!user || user.is_organization_first_user !== false || wasWelcomeDismissed(user.uuid, user.organization?.id)) {
        return null
    }
    return <WelcomeDialog />
}

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}

export function ProjectHomepage(): JSX.Element {
    return (
        <div className="flex-1 min-h-0">
            <AiFirstHomepage />
            <MaybeWelcomeDialog />
        </div>
    )
}
