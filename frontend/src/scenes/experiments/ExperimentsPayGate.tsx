import { PayGatePage } from 'lib/components/PayGatePage/PayGatePage'

import { AvailableFeature } from '~/types'

export function ExperimentsPayGate(): JSX.Element {
    return (
        <PayGatePage
            featureKey={AvailableFeature.EXPERIMENTATION}
            header={
                <>
                    Introducing <span className="highlight">Experimentation</span>!
                </>
            }
            caption="Improve your product by A/B testing new features to discover what works best for your users."
            docsLink="https://posthog.com/docs/user-guides/experimentation"
        />
    )
}
