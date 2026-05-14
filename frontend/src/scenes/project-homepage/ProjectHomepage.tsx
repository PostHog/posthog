import './ProjectHomepage.scss'

import { useValues } from 'kea'
import { useState } from 'react'

import { ConciergeModal } from 'lib/components/ConciergeModal/ConciergeModal'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
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
    const [showConcierge, setShowConcierge] = useState(false)

    return (
        <div className="flex-1 min-h-0">
            <AiFirstHomepage />
            <MaybeWelcomeDialog />

            {/* TEMP: test button — remove before merging */}
            <div className="fixed bottom-4 right-4 z-50">
                <LemonButton type="primary" onClick={() => setShowConcierge(true)}>
                    Open concierge modal
                </LemonButton>
            </div>
            <ConciergeModal
                isOpen={showConcierge}
                onClose={() => setShowConcierge(false)}
                notificationId="test-123"
                title="Test notification"
                body={JSON.stringify({
                    body: 'Dear Sarah,\n\nThis is your CSM, Christophe. I am checking back in after our call yesterday. I wanted to share a few things I noticed in your project that might help your team get more value from PostHog.\n\nCheers,\nChristophe',
                    call_to_action: 'Run this skill',
                    notification_style: 'royal',
                })}
            />
        </div>
    )
}
