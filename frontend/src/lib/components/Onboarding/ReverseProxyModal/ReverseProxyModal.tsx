import { LemonDivider, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { reverseProxyModalLogic } from './ReverseProxyModalLogic'

export function ReverseProxyModal(): JSX.Element {
    const { isOpen } = useValues(reverseProxyModalLogic)
    const { closeReverseProxyModal } = useActions(reverseProxyModalLogic)
    return (
        <div>
            <LemonModal
                isOpen={isOpen}
                onClose={() => {
                    closeReverseProxyModal()
                }}
                width={800}
                title={<>Setup Reverse Proxy</>}
                description={
                    <p>
                        A reverse proxy enables you to send events to PostHog Cloud using your own domain. Using a
                        reverse proxy means that events are less likely to be intercepted by tracking blockers.
                    </p>
                }
                footer={
                    <>
                        <LemonButton
                            onClick={() => {
                                closeReverseProxyModal()
                            }}
                            type="secondary"
                        >
                            Close
                        </LemonButton>
                    </>
                }
            >
                <h3>Deploying Your Own Reverse Proxy</h3>
                <div className="flex flex-col p-2">
                    <p className="font-normal">
                        You can read more about how to setup and deploy your own reverse proxy{' '}
                        <Link
                            to="https://posthog.com/docs/advanced/proxy"
                            target="_blank"
                            targetBlankIcon
                            disableDocsPanel
                        >
                            here
                        </Link>
                    </p>
                </div>
                <LemonDivider label="OR" />
                <h3>Managed Reverse Proxy</h3>
                <div className="flex flex-col p-2">
                    <p className="font-normal">
                        We also offer a managed reverse proxy service, simplifying the deployment and management of your
                        PostHog.{' '}
                        <Link
                            to="https://posthog.com/docs/advanced/proxy/managed-reverse-proxy"
                            target="_blank"
                            targetBlankIcon
                            disableDocsPanel
                        >
                            Read the docs here
                        </Link>
                    </p>
                </div>
            </LemonModal>
        </div>
    )
}
