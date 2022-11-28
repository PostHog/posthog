import { toolbarRedirectLogic } from './toolbarRedirectLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { useValues } from 'kea'
import { LemonModal } from 'lib/components/LemonModal'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export function ToolbarRedirectModal(): JSX.Element {
    const { redirect, domain } = useValues(toolbarRedirectLogic)

    return (
        <LemonModal
            isOpen={!!redirect}
            footer={
                <>
                    <div className="flex flex-1">
                        <LemonButton
                            type="tertiary"
                            status="stealth"
                            to="https://posthog.com/manual/toolbar"
                            targetBlank
                        >
                            Can't connect?
                        </LemonButton>
                    </div>
                    <LemonButton onClick={() => router.actions.push(urls.toolbarLaunch())} type="secondary">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        to={`/api/user/redirect_to_site/?appUrl=${redirect}`}
                        onClick={(e) => {
                            e.preventDefault()
                            window.location.href = `/api/user/redirect_to_site/?appUrl=${redirect}`
                        }}
                        type="primary"
                    >
                        Authorize {domain}
                    </LemonButton>
                </>
            }
            onClose={() => router.actions.push(urls.toolbarLaunch())}
            title="Launch Toolbar"
        >
            <p>
                You're about to grant code running on{' '}
                <strong>
                    <code>{domain}</code>
                </strong>{' '}
                access to your PostHog account.
            </p>
            <p>
                Launch at:{' '}
                <strong>
                    <code>{redirect}</code>
                </strong>
            </p>
        </LemonModal>
    )
}
