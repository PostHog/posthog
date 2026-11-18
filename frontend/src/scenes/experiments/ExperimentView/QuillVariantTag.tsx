import { useValues } from 'kea'

import { Badge, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { getExperimentVariants, getVariantColor } from '~/scenes/experiments/utils'

import { EXPERIMENT_VARIANT_MULTIPLE } from 'products/experiments/frontend/constants'

import { MULTIPLE_VARIANT_HELP } from '../MetricsView/new/metricsTableCopy'

/** The quill twin of VariantTag: the variant's color dot and key. */
export function QuillVariantTag({ variantKey }: { variantKey: string }): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    if (variantKey === EXPERIMENT_VARIANT_MULTIPLE) {
        return (
            <Tooltip>
                <TooltipTrigger render={<Badge variant="destructive" tabIndex={0} />}>{variantKey}</TooltipTrigger>
                <TooltipContent className="max-w-80">{MULTIPLE_VARIANT_HELP}</TooltipContent>
            </Tooltip>
        )
    }

    if (experiment.holdout && variantKey === `holdout-${experiment.holdout_id}`) {
        return <Badge>{experiment.holdout.name}</Badge>
    }

    return (
        <span className="flex min-w-0 items-center gap-2">
            <span
                className="size-2 shrink-0 rounded-full"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: getVariantColor(variantKey, getExperimentVariants(experiment)) }}
            />
            <Text size="xs" weight="semibold" className="truncate" render={<span />}>
                {variantKey}
            </Text>
        </span>
    )
}
