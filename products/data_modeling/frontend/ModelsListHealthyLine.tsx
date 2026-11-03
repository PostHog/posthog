import { useValues } from 'kea'

import * as float from '@posthog/brand/hoggies/png/float'
import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'

import { materializedModelsMessage } from './healthyMessage'
import { modelsOverviewLogic } from './modelsOverviewLogic'

const HedgehogFloat = pngHoggie(float)
const HEALTHY_SUMMARY = 'No failed, suspended or stale models, and no failing checks on them.'

export function ModelsListHealthyLine(): JSX.Element {
    const { refreshSummary } = useValues(modelsOverviewLogic)
    const materializedMessage = materializedModelsMessage(refreshSummary.materializedCount)
    return (
        <Item variant="outline" size="sm" data-attr="models-list-healthy">
            <ItemMedia>
                <HedgehogFloat className="w-14" />
            </ItemMedia>
            <ItemContent>
                <ItemTitle>Nothing needs attention</ItemTitle>
                <ItemDescription>
                    <span>{HEALTHY_SUMMARY}</span>
                    {materializedMessage && <span>{` ${materializedMessage}`}</span>}
                    {refreshSummary.lastRefreshAt && (
                        <span>
                            {' Last refresh '}
                            <TZLabel time={refreshSummary.lastRefreshAt} />.
                        </span>
                    )}
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
