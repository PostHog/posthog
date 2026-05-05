import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

interface LiveOpenInsightButtonProps {
    to: string
    label?: string
    title?: string
}

export const LiveOpenInsightButton = ({
    to,
    label = 'Open as new insight',
    title,
}: LiveOpenInsightButtonProps): JSX.Element => (
    <LemonButton
        to={to}
        icon={<IconOpenInNew />}
        size="xsmall"
        type="secondary"
        tooltip={title ?? label}
        onClick={() => {
            void addProductIntentForCrossSell({
                from: ProductKey.WEB_ANALYTICS,
                to: ProductKey.PRODUCT_ANALYTICS,
                intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
            })
        }}
    >
        {label}
    </LemonButton>
)
