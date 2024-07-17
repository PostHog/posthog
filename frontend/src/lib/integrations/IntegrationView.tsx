import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'

import { IntegrationType } from '~/types'

export function IntegrationView({
    integration,
    suffix,
}: {
    integration: IntegrationType
    suffix?: JSX.Element
}): JSX.Element {
    return (
        <div className="rounded border flex justify-between items-center p-2 bg-bg-light">
            <div className="flex items-center gap-4 ml-2">
                <img src={integration.icon_url} className="h-10 w-10 rounded" />
                <div>
                    <div>
                        Connected to <strong>{integration.name}</strong>
                    </div>
                    {integration.created_by ? (
                        <UserActivityIndicator
                            at={integration.created_at}
                            by={integration.created_by}
                            prefix="Updated"
                            className="text-muted"
                        />
                    ) : null}
                </div>
            </div>

            {suffix}
        </div>
    )
}
