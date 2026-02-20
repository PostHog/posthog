import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

export function TwigSlackIntegration(): JSX.Element {
    const { twigSlackIntegrations, twigSlackAvailable } = useValues(integrationsLogic)

    return (
        <div>
            <p>
                Connect Slack to Twig to kick off tasks like pull requests directly from Slack.
            </p>

            <div className="deprecated-space-y-2">
                {twigSlackIntegrations?.map((integration) => (
                    <IntegrationView key={integration.id} integration={integration} />
                ))}

                <div>
                    {twigSlackAvailable ? (
                        <Link to={api.integrations.authorizeUrl({ kind: 'slack-twig' })} disableClientSideRouting>
                            <img
                                alt="Add to Slack"
                                height="40"
                                width="139"
                                src="https://platform.slack-edge.com/img/add_to_slack.png"
                                srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                            />
                        </Link>
                    ) : (
                        <p className="text-secondary">
                            The Twig Slack integration is not configured for this instance.
                        </p>
                    )}
                </div>
            </div>
        </div>
    )
}
