import { useActions } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

/**
 * Shown when a scene's code fails to import, or its logic throws while mounting. Without it the
 * address bar moves to the new scene while the old one stays rendered, so the person is left on a
 * page that no longer matches the URL.
 */
export function SceneLoadError(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    return (
        <div className="p-4">
            <h1 className="mb-1 text-2xl font-bold">Couldn't load this page</h1>
            <p>
                Something went wrong while this page was loading. Reload to try again. If it keeps happening, let us
                know.
            </p>
            <div className="flex gap-2 flex-wrap">
                <LemonButton
                    type="primary"
                    icon={<IconRefresh />}
                    onClick={() => window.location.reload()}
                    data-attr="scene-load-error-reload"
                >
                    Reload the page
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={() => openSupportForm({ kind: 'bug', isEmailFormOpen: true })}
                    data-attr="scene-load-error-email-engineer"
                >
                    Email an engineer
                </LemonButton>
            </div>
        </div>
    )
}
