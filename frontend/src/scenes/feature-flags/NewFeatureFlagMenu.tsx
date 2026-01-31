import { IconCode, IconFlask, IconTestTube, IconToggle } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

type FeatureFlagNewType = 'boolean' | 'multivariate' | 'remote_config'

interface FeatureFlagTypeMetadata {
    name: string
    description: string
    icon: React.ComponentType
    url: string
}

const FEATURE_FLAG_TYPE_METADATA: Record<FeatureFlagNewType, FeatureFlagTypeMetadata> = {
    boolean: {
        name: 'Boolean flag',
        description: 'Simple on/off toggle for feature releases',
        icon: IconToggle,
        url: urls.featureFlagNew({ type: 'boolean' }),
    },
    multivariate: {
        name: 'Multivariate flag',
        description: 'Multiple variants with rollout percentages',
        icon: IconTestTube,
        url: urls.featureFlagNew({ type: 'multivariate' }),
    },
    remote_config: {
        name: 'Remote config',
        description: 'Deliver configuration values to your app',
        icon: IconCode,
        url: urls.featureFlagNew({ type: 'remote_config' }),
    },
}

const FLAG_TYPES: FeatureFlagNewType[] = ['boolean', 'multivariate', 'remote_config']

export function OverlayForNewFeatureFlagMenu({ dataAttr }: { dataAttr: string }): JSX.Element {
    return (
        <>
            {FLAG_TYPES.map((flagType) => {
                const metadata = FEATURE_FLAG_TYPE_METADATA[flagType]
                return (
                    <LemonButton
                        key={flagType}
                        icon={<metadata.icon />}
                        to={metadata.url}
                        data-attr={dataAttr}
                        data-attr-flag-type={flagType}
                        fullWidth
                    >
                        <div className="flex flex-col text-sm py-1">
                            <strong>{metadata.name}</strong>
                            <span className="text-xs font-sans font-normal">{metadata.description}</span>
                        </div>
                    </LemonButton>
                )
            })}
            <LemonDivider className="my-1" />
            <LemonButton
                icon={<IconFlask />}
                to={urls.experiment('new')}
                data-attr={dataAttr}
                data-attr-flag-type="experiment"
                onClick={() => {
                    void addProductIntentForCrossSell({
                        from: ProductKey.FEATURE_FLAGS,
                        to: ProductKey.EXPERIMENTS,
                        intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                    })
                }}
                fullWidth
            >
                <div className="flex flex-col text-sm py-1">
                    <strong>Experiment</strong>
                    <span className="text-xs font-sans font-normal">Run A/B tests with statistical analysis</span>
                </div>
            </LemonButton>
        </>
    )
}
