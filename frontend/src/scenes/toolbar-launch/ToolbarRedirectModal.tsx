import { toolbarRedirectLogic } from './toolbarRedirectLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { useValues } from 'kea'
import { LemonModal } from 'lib/components/LemonModal'

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
                    <LemonButton type="secondary">Cancel</LemonButton>
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
            onAfterClose={function Ke() {}}
            onClose={function Ke() {}}
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
