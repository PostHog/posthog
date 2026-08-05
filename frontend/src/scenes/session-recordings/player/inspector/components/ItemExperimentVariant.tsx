import { LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { InspectorListItemExperimentVariant } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

export interface ItemExperimentVariantProps {
    item: InspectorListItemExperimentVariant
}

export function ItemExperimentVariant({ item }: ItemExperimentVariantProps): JSX.Element {
    return (
        <div data-attr="item-experiment-variant" className="font-light w-full">
            <div className="flex flex-row w-full gap-2 items-center px-2 py-1 text-xs">
                <div className="truncate flex-1 min-w-0 font-medium">Experiment variant assigned</div>
                <div className="flex items-center gap-1 shrink-0 text-secondary">
                    <span className="truncate max-w-[40ch]" title={item.data.experimentName}>
                        {item.data.experimentName}
                    </span>
                </div>
            </div>
        </div>
    )
}

export function ItemExperimentVariantDetail({ item }: ItemExperimentVariantProps): JSX.Element {
    const { experimentId, experimentName, flagKey, variant, multipleVariants, variantsSeen } = item.data

    return (
        <div data-attr="item-experiment-variant" className="font-light w-full">
            <div className="px-2 py-1 text-xs border-t flex flex-col gap-1">
                <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="text-secondary shrink-0">Experiment</span>
                    <Link
                        to={urls.experiment(experimentId)}
                        target="_blank"
                        className="truncate"
                        onClick={() => {
                            void addProductIntentForCrossSell({
                                from: ProductKey.SESSION_REPLAY,
                                to: ProductKey.EXPERIMENTS,
                                intent_context: ProductIntentContext.SESSION_REPLAY_EXPERIMENT_LINK_CLICKED,
                                metadata: { experiment_id: experimentId },
                            })
                        }}
                    >
                        {experimentName}
                    </Link>
                </div>
                <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="text-secondary shrink-0">Variant</span>
                    <span className="truncate">{variant}</span>
                </div>
                <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="text-secondary shrink-0">Feature flag</span>
                    <span className="truncate">{flagKey}</span>
                </div>
                {multipleVariants ? (
                    <div className="flex items-center justify-between gap-2 min-w-0">
                        <span className="text-secondary shrink-0">Variants seen</span>
                        <LemonTag type="warning">{variantsSeen.join(', ')}</LemonTag>
                    </div>
                ) : null}
            </div>
        </div>
    )
}
