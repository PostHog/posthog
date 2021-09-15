import { clamp, compactNumber, humanFriendlyDuration } from 'lib/utils'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { getChartColors } from 'lib/colors'
import api from 'lib/api'
import {
    FilterType,
    FunnelStepRangeEntityFilter,
    FunnelRequestParams,
    FunnelResult,
    FunnelStep,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    FunnelsTimeConversionBins,
} from '~/types'

const PERCENTAGE_DISPLAY_PRECISION = 1 // Number of decimals to show in percentages

export function formatDisplayPercentage(percentage: number): string {
    if (Number.isNaN(percentage)) {
        percentage = 0
    }
    // Returns a formatted string properly rounded to ensure consistent results
    return (percentage * 100).toFixed(PERCENTAGE_DISPLAY_PRECISION)
}

export function getReferenceStep<T>(steps: T[], stepReference: FunnelStepReference, index?: number): T {
    // Step to serve as denominator of percentage calculations.
    // step[0] is full-funnel conversion, previous is relative.
    if (!index || index <= 0) {
        return steps[0]
    }
    switch (stepReference) {
        case FunnelStepReference.previous:
            return steps[index - 1]
        case FunnelStepReference.total:
        default:
            return steps[0]
    }
}

// Gets last filled step if steps[index] is empty.
// Useful in calculating total and average times for total conversions where the last step has 0 count
export function getLastFilledStep(steps: FunnelStep[], index?: number): FunnelStep {
    const firstIndex = Math.min(steps.length, Math.max(0, index || steps.length - 1)) + 1
    return (
        steps
            .slice(0, firstIndex)
            .reverse()
            .find((s) => s.count > 0) || steps[0]
    )
}

export function humanizeOrder(order: number): number {
    return order + 1
}

export function getSeriesColor(index?: number): string | undefined {
    if (typeof index === 'number' && index >= 0) {
        return getChartColors('white')[index]
    }
}

export function getBreakdownMaxIndex(breakdown?: FunnelStep[]): number | undefined {
    // Returns the index of the last nonzero breakdown item
    if (!breakdown) {
        return
    }
    const nonZeroCounts = breakdown.map(({ count }, index) => ({ count, index })).filter(({ count }) => !!count)
    if (!nonZeroCounts.length) {
        return
    }
    return nonZeroCounts[nonZeroCounts.length - 1].index
}

export function createPopoverMetrics(
    breakdown: Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'>,
    currentOrder = 0,
    previousOrder = 0
): { title: string; value: number | string; visible?: boolean }[] {
    return [
        {
            title: 'Completed step',
            value: breakdown.count,
        },
        {
            title: 'Conversion rate (total)',
            value: formatDisplayPercentage(breakdown.conversionRates.total) + '%',
        },
        {
            title: `Conversion rate (from step ${humanizeOrder(previousOrder)})`,
            value: formatDisplayPercentage(breakdown.conversionRates.fromPrevious) + '%',
            visible: currentOrder !== 0,
        },
        {
            title: 'Dropped off',
            value: breakdown.droppedOffFromPrevious,
            visible: currentOrder !== 0 && breakdown.droppedOffFromPrevious > 0,
        },
        {
            title: `Dropoff rate (from step ${humanizeOrder(previousOrder)})`,
            value: formatDisplayPercentage(1 - breakdown.conversionRates.fromPrevious) + '%',
            visible: currentOrder !== 0 && breakdown.droppedOffFromPrevious > 0,
        },
        {
            title: 'Average time on step',
            value: humanFriendlyDuration(breakdown.average_conversion_time),
            visible: !!breakdown.average_conversion_time,
        },
    ]
}

export function getSeriesPositionName(
    index?: number,
    breakdownMaxIndex?: number
): 'first' | 'last' | 'only' | undefined {
    if (!breakdownMaxIndex) {
        return 'only'
    }
    if (typeof index === 'number') {
        return index === 0 ? 'first' : index === breakdownMaxIndex ? 'last' : undefined
    }
    return
}

export function humanizeStepCount(count?: number): string {
    if (typeof count === 'undefined') {
        return ''
    }
    return count > 9999 ? compactNumber(count) : count.toLocaleString()
}

export function cleanBinResult(binsResult: FunnelsTimeConversionBins): FunnelsTimeConversionBins {
    return {
        ...binsResult,
        bins: binsResult.bins.map(([time, count]) => [time ?? 0, count ?? 0]),
        average_conversion_time: binsResult.average_conversion_time ?? 0,
    }
}

export function aggregateBreakdownResult(
    breakdownList: FunnelStep[][],
    breakdownProperty?: string | number | number[]
): FunnelStepWithNestedBreakdown[] {
    if (breakdownList.length) {
        // Create mapping to determine breakdown ordering by first step counts
        const breakdownToOrderMap = breakdownList
            .reduce(
                (allEntries, breakdownSteps) => [
                    ...allEntries,
                    {
                        breakdown_value: breakdownSteps?.[0]?.breakdown_value ?? 'Other',
                        count: breakdownSteps?.[0]?.count ?? 0,
                    },
                ],
                []
            )
            .sort((a, b) => b.count - a.count)
            .reduce(
                (allEntries, breakdown, order) => ({
                    ...allEntries,
                    [breakdown.breakdown_value]: { ...breakdown, order },
                }),
                {}
            )

        return breakdownList[0].map((step, i) => ({
            ...step,
            count: breakdownList.reduce((total, breakdownSteps) => total + breakdownSteps[i].count, 0),
            breakdown: breakdownProperty,
            nested_breakdown: breakdownList
                .reduce(
                    (allEntries, breakdownSteps) => [
                        ...allEntries,
                        {
                            ...breakdownSteps[i],
                            order: breakdownToOrderMap[breakdownSteps[i].breakdown_value].order,
                        },
                    ],
                    []
                )
                .sort((a, b) => a.order - b.order),
            average_conversion_time: null,
            people: [],
        }))
    }
    return []
}

export function isBreakdownFunnelResults(results: FunnelStep[] | FunnelStep[][]): results is FunnelStep[][] {
    return Array.isArray(results) && (results.length === 0 || Array.isArray(results[0]))
}

// breakdown parameter could be a string (property breakdown) or object/number (list of cohort ids)
export function isValidBreakdownParameter(breakdown: FunnelRequestParams['breakdown']): boolean {
    return ['string', 'null', 'undefined', 'number'].includes(typeof breakdown) || Array.isArray(breakdown)
}

export function wait(ms = 1000): Promise<any> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

export const SECONDS_TO_POLL = 3 * 60

export const EMPTY_FUNNEL_RESULTS = {
    results: [],
    timeConversionResults: {
        bins: [],
        average_conversion_time: 0,
    },
}

export async function pollFunnel<T = FunnelStep[]>(apiParams: FunnelRequestParams): Promise<FunnelResult<T>> {
    // Tricky: This API endpoint has wildly different return types depending on parameters.
    const { refresh, ...bodyParams } = apiParams
    let result = await api.create('api/insight/funnel/?' + (refresh ? 'refresh=true' : ''), bodyParams)
    const start = window.performance.now()
    while (result.result.loading && (window.performance.now() - start) / 1000 < SECONDS_TO_POLL) {
        await wait()
        result = await api.create('api/insight/funnel', bodyParams)
    }
    // if endpoint is still loading after 3 minutes just return default
    if (result.loading) {
        throw { status: 0, statusText: 'Funnel timeout' }
    }
    return result

    // return {result:[[{action_id:"$pageview",name:"$pageview",order:0,people:["0178ac0c-da3a-0022-4fa4-85899123f0ec","0178ac0c-da39-0001-a4f1-6103c6014035","0178ac0c-da3a-0016-d69f-e5c16c17d035","0178ac0c-da3a-0028-ffbd-d6ac3c2c8223","0178ac0c-da3a-0003-3e6b-6163692c5bac","0178ac0c-da3a-0019-9e8f-ee74f5025b55","0178ac0c-da3a-0000-1e35-0f027919f204","0178ac0c-da39-0004-e84a-d50409f34329","0178ac0c-da39-0005-1eff-2b4d8de3c702","0178ac0c-da3b-0003-ff5e-0ce99ad74a44","0178ac0c-da3b-001e-309e-79442228f1ad","0178ac0c-da3b-0017-d37b-959263a4263e","0178ac0c-da3b-0019-33ae-cbc582906362","0178ac0c-da3b-001d-5488-8044cde8b619","0178ac0c-da3b-0028-c997-072f19e56f53","0178ac0c-da3a-0021-eb9b-8d601c02249f","0178ac0c-da3a-0010-2b08-13ca438a50b5","0178ac0c-da3b-001c-c24c-fbb74917a649","0178ac0c-da3a-0025-2c91-34f6c2e99b7e","0178ac0c-da3a-0027-bd1d-e97f2587cc7f","0178ac0c-da3b-0020-abb2-cccaa3b3b710","0178ac0c-da3b-000f-589f-5a0d5b13e739","0178ac0c-da3b-0006-9ed6-61b9ce5eb106","0178ac0c-da3b-0009-c0c8-dfb3ac46bf77","0178ac0c-da3b-0026-1672-8b55c05d8906","0178ac0c-da3b-0002-04d1-b2377e3f0f31","0178ac0c-da3a-0005-ea83-431ca4770f47","0178ac0c-da3b-0012-274b-f51364ab2ba3","0178ac0c-da3b-0013-860a-df9494d489ba","0178ac0c-da3a-0026-c290-6bec04f15871","0178ac0c-da3b-0005-5ba7-a70d98c4438e","0178ac0c-da3b-001b-79d3-de4337531a13","0178ac0c-da3c-0000-8b91-aeb6c6d3ffb9","0178ac0c-da3b-0023-7814-c3f8466a7c8f","0178ac0c-da3b-000e-b462-08acc517afff","0178ac0c-da3b-0014-002d-e5845f209327","0178ac0c-da39-0000-908f-b74d6cbfd3a1","0178ac0c-da3b-0010-6863-e80243afe211","0178ac0c-da3a-000d-da6f-259d7407d077","0178ac0c-da3b-0016-2627-60bf3142e865","0178ac0c-da39-0007-a74f-00a7fbceb356","0178ac0c-da3a-000f-02dc-19677a090373","0178ac0c-da3b-0025-5c7d-fe85ce39dac1","0178ac0c-da3a-001c-a623-2e439a7e2757","0178ac0c-da3a-0011-b726-0902273fd79c","0178ac0c-da3a-0023-07eb-b85f83179a9d","0178ac0c-da3a-0007-aab0-76d10ff9658c","0178ac0c-da3b-002a-6a71-3b7a503aee5c","0178ac0c-da3a-0018-c3da-300537b37de3","0178ac0c-da3b-000a-8328-4978c7282b10","0178ac0c-da3b-001a-3cbf-712ec7c95d56","0178ac0c-da39-0006-666c-5e55443921a1","0178ac0c-da3a-001e-3823-31ace73bab0f","0178ac0c-da3b-0007-c118-137156a1e58e","0178ac0c-da3a-000b-fd39-13f6de576959","0178ac0c-da3c-0004-7a83-5f04f542811f","0178ac0c-da3b-0001-c08d-41b99bd84ea5","0178ac0c-da39-0003-70b5-38d170bdbc42","0178ac0c-da39-0008-059b-fd4c5492768d","0178ac0c-da3b-0000-f9ab-7894f8f0f24e","0178ac0c-da3c-0003-0824-fab9194a479d","0178ac0c-da3b-000c-0181-27e9878cb04e","0178ac0c-da3b-0021-0411-6e57115a3c5b","0178ac0c-da3a-0020-ab22-f222bfb4e8cf","0178ac0c-da3a-001a-d774-960c8ee1b620","0178ac0c-da3a-001b-f452-ea4ef277616f","0178ac0c-da3a-0015-32e9-d5f737539d01","0178ac0c-da3a-000a-9583-0ef277ac823a","0178ac0c-da3a-0012-f179-24ea07a32603","0178ac0c-da3b-0008-c880-7f2013ab26c7","0178ac0c-da3c-0001-4a56-6ea6f194d4a8","0178ac0c-da3b-0027-c3b8-1b2786d84b8e","0178ac0c-da3b-0029-8d9c-2e97b1d4e96b","0178ac0c-da3b-001f-3b32-265a348e0d6f","0178ac0c-da3a-0013-970d-b01fc1a4bb5a","0178ac0c-da3b-0011-0c21-d1bd96504728","0178ac0c-da3b-0024-eb96-8a41d41139a5","0178ac0c-da3b-0015-a6b8-9f447936256f","0178ac0c-da3a-001d-3aae-69d3977000f1","0178ac0c-da3a-0006-dd54-bd9d8e48ec79","0178ac0c-da3b-000b-9499-1907f0ee0cb3","0178ac0c-da3a-0008-9634-d0cc97a671fb","0178ac0c-da3a-0017-f515-3a03a0607469","0178ac0c-da3c-0005-2c50-5e47233496e4","0178ac0c-da3a-0024-5db0-2c233dd5a13f","0178ac0c-da3a-0009-d079-5daf52bf8e24","0178ac0c-da3a-0029-89b6-9d67f23a7a64","0178ac0c-da3c-0002-c73a-135bda8899bc","0178ac0c-da3a-001f-dc7f-582e6309a74d","0178ac0c-da3a-000e-d3b1-4cfcda94f9dd","0178ac0c-da39-0002-b722-9fe47dd8cfb0","0178ac0c-da3a-0002-5605-5d814c9167b9","0178ac0c-da3b-0022-0fb2-e9e183e0e0ba","0178ac0c-da3a-0004-6e95-441e44e1063f","0178ac0c-da3b-000d-4632-354048ace791","0178ac0c-e0ad-0004-bda3-11ed21e272de","0178ac0c-e0ad-0003-8c2a-91e14049b5f6","0178ac0c-e0ad-000f-ac65-3bbea6e2990c","0178ac0c-e0ad-0000-cbe5-b48816ead63a","0178ac0c-e0ad-000a-58f8-a7146659562b"],count:120,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"",breakdown_value:""},{action_id:"$pageview",name:"$pageview",order:1,people:["0178ac0c-da3a-0022-4fa4-85899123f0ec","0178ac0c-da39-0001-a4f1-6103c6014035","0178ac0c-da3a-0016-d69f-e5c16c17d035","0178ac0c-da3a-0028-ffbd-d6ac3c2c8223","0178ac0c-da3a-0003-3e6b-6163692c5bac","0178ac0c-da3a-0019-9e8f-ee74f5025b55","0178ac0c-da3a-0000-1e35-0f027919f204","0178ac0c-da39-0004-e84a-d50409f34329","0178ac0c-da39-0005-1eff-2b4d8de3c702","0178ac0c-da3b-0003-ff5e-0ce99ad74a44","0178ac0c-da3b-001e-309e-79442228f1ad","0178ac0c-da3b-0017-d37b-959263a4263e","0178ac0c-da3b-0019-33ae-cbc582906362","0178ac0c-da3b-001d-5488-8044cde8b619","0178ac0c-da3b-0028-c997-072f19e56f53","0178ac0c-da3a-0021-eb9b-8d601c02249f","0178ac0c-da3a-0010-2b08-13ca438a50b5","0178ac0c-da3b-001c-c24c-fbb74917a649","0178ac0c-da3a-0025-2c91-34f6c2e99b7e","0178ac0c-da3a-0027-bd1d-e97f2587cc7f","0178ac0c-da3b-0020-abb2-cccaa3b3b710","0178ac0c-da3b-000f-589f-5a0d5b13e739","0178ac0c-da3b-0006-9ed6-61b9ce5eb106","0178ac0c-da3b-0009-c0c8-dfb3ac46bf77","0178ac0c-da3b-0026-1672-8b55c05d8906","0178ac0c-da3b-0002-04d1-b2377e3f0f31","0178ac0c-da3a-0005-ea83-431ca4770f47","0178ac0c-da3b-0012-274b-f51364ab2ba3","0178ac0c-da3b-0013-860a-df9494d489ba","0178ac0c-da3a-0026-c290-6bec04f15871","0178ac0c-da3b-0005-5ba7-a70d98c4438e","0178ac0c-da3b-001b-79d3-de4337531a13","0178ac0c-da3c-0000-8b91-aeb6c6d3ffb9","0178ac0c-da3b-0023-7814-c3f8466a7c8f","0178ac0c-da3b-000e-b462-08acc517afff","0178ac0c-da3b-0014-002d-e5845f209327","0178ac0c-da39-0000-908f-b74d6cbfd3a1","0178ac0c-da3b-0010-6863-e80243afe211","0178ac0c-da3a-000d-da6f-259d7407d077","0178ac0c-da3b-0016-2627-60bf3142e865","0178ac0c-da39-0007-a74f-00a7fbceb356","0178ac0c-da3a-000f-02dc-19677a090373","0178ac0c-da3b-0025-5c7d-fe85ce39dac1","0178ac0c-da3a-001c-a623-2e439a7e2757","0178ac0c-da3a-0011-b726-0902273fd79c","0178ac0c-da3a-0023-07eb-b85f83179a9d","0178ac0c-da3a-0007-aab0-76d10ff9658c","0178ac0c-da3b-002a-6a71-3b7a503aee5c","0178ac0c-da3a-0018-c3da-300537b37de3","0178ac0c-da3b-000a-8328-4978c7282b10","0178ac0c-da3b-001a-3cbf-712ec7c95d56","0178ac0c-da39-0006-666c-5e55443921a1","0178ac0c-da3a-001e-3823-31ace73bab0f","0178ac0c-da3b-0007-c118-137156a1e58e","0178ac0c-da3a-000b-fd39-13f6de576959","0178ac0c-da3c-0004-7a83-5f04f542811f","0178ac0c-da3b-0001-c08d-41b99bd84ea5","0178ac0c-da39-0003-70b5-38d170bdbc42","0178ac0c-da39-0008-059b-fd4c5492768d","0178ac0c-da3b-0000-f9ab-7894f8f0f24e","0178ac0c-da3c-0003-0824-fab9194a479d","0178ac0c-da3b-000c-0181-27e9878cb04e","0178ac0c-da3b-0021-0411-6e57115a3c5b","0178ac0c-da3a-0020-ab22-f222bfb4e8cf","0178ac0c-da3a-001a-d774-960c8ee1b620","0178ac0c-da3a-001b-f452-ea4ef277616f","0178ac0c-da3a-0015-32e9-d5f737539d01","0178ac0c-da3a-000a-9583-0ef277ac823a","0178ac0c-da3a-0012-f179-24ea07a32603","0178ac0c-da3b-0008-c880-7f2013ab26c7","0178ac0c-da3c-0001-4a56-6ea6f194d4a8","0178ac0c-da3b-0027-c3b8-1b2786d84b8e","0178ac0c-da3b-0029-8d9c-2e97b1d4e96b","0178ac0c-da3b-001f-3b32-265a348e0d6f","0178ac0c-da3a-0013-970d-b01fc1a4bb5a","0178ac0c-da3b-0011-0c21-d1bd96504728","0178ac0c-da3b-0024-eb96-8a41d41139a5","0178ac0c-da3b-0015-a6b8-9f447936256f","0178ac0c-da3a-001d-3aae-69d3977000f1","0178ac0c-da3a-0006-dd54-bd9d8e48ec79","0178ac0c-da3b-000b-9499-1907f0ee0cb3","0178ac0c-da3a-0008-9634-d0cc97a671fb","0178ac0c-da3a-0017-f515-3a03a0607469","0178ac0c-da3c-0005-2c50-5e47233496e4","0178ac0c-da3a-0024-5db0-2c233dd5a13f","0178ac0c-da3a-0009-d079-5daf52bf8e24","0178ac0c-da3a-0029-89b6-9d67f23a7a64","0178ac0c-da3c-0002-c73a-135bda8899bc","0178ac0c-da3a-001f-dc7f-582e6309a74d","0178ac0c-da3a-000e-d3b1-4cfcda94f9dd","0178ac0c-da39-0002-b722-9fe47dd8cfb0","0178ac0c-da3a-0002-5605-5d814c9167b9","0178ac0c-da3b-0022-0fb2-e9e183e0e0ba"],count:93,type:"events",average_conversion_time:15,median_conversion_time:15,breakdown:"",breakdown_value:""},{action_id:"$pageview",name:"$pageview",order:2,people:["0178ac0c-da3a-0022-4fa4-85899123f0ec","0178ac0c-da39-0001-a4f1-6103c6014035","0178ac0c-da3a-0016-d69f-e5c16c17d035","0178ac0c-da3a-0028-ffbd-d6ac3c2c8223","0178ac0c-da3a-0003-3e6b-6163692c5bac","0178ac0c-da3a-0019-9e8f-ee74f5025b55","0178ac0c-da3a-0000-1e35-0f027919f204","0178ac0c-da39-0004-e84a-d50409f34329","0178ac0c-da39-0005-1eff-2b4d8de3c702","0178ac0c-da3b-0003-ff5e-0ce99ad74a44","0178ac0c-da3b-001e-309e-79442228f1ad","0178ac0c-da3b-0017-d37b-959263a4263e","0178ac0c-da3b-0019-33ae-cbc582906362","0178ac0c-da3b-001d-5488-8044cde8b619","0178ac0c-da3b-0028-c997-072f19e56f53","0178ac0c-da3a-0021-eb9b-8d601c02249f","0178ac0c-da3a-0010-2b08-13ca438a50b5","0178ac0c-da3b-001c-c24c-fbb74917a649","0178ac0c-da3a-0025-2c91-34f6c2e99b7e","0178ac0c-da3a-0027-bd1d-e97f2587cc7f","0178ac0c-da3b-0020-abb2-cccaa3b3b710","0178ac0c-da3b-000f-589f-5a0d5b13e739","0178ac0c-da3b-0006-9ed6-61b9ce5eb106","0178ac0c-da3b-0009-c0c8-dfb3ac46bf77","0178ac0c-da3b-0026-1672-8b55c05d8906","0178ac0c-da3b-0002-04d1-b2377e3f0f31","0178ac0c-da3a-0005-ea83-431ca4770f47","0178ac0c-da3b-0012-274b-f51364ab2ba3","0178ac0c-da3b-0013-860a-df9494d489ba","0178ac0c-da3a-0026-c290-6bec04f15871","0178ac0c-da3b-0005-5ba7-a70d98c4438e","0178ac0c-da3b-001b-79d3-de4337531a13","0178ac0c-da3c-0000-8b91-aeb6c6d3ffb9","0178ac0c-da3b-0023-7814-c3f8466a7c8f","0178ac0c-da3b-000e-b462-08acc517afff","0178ac0c-da3b-0014-002d-e5845f209327","0178ac0c-da39-0000-908f-b74d6cbfd3a1","0178ac0c-da3b-0010-6863-e80243afe211","0178ac0c-da3a-000d-da6f-259d7407d077","0178ac0c-da3b-0016-2627-60bf3142e865","0178ac0c-da39-0007-a74f-00a7fbceb356","0178ac0c-da3a-000f-02dc-19677a090373","0178ac0c-da3b-0025-5c7d-fe85ce39dac1","0178ac0c-da3a-001c-a623-2e439a7e2757","0178ac0c-da3a-0011-b726-0902273fd79c","0178ac0c-da3a-0023-07eb-b85f83179a9d","0178ac0c-da3a-0007-aab0-76d10ff9658c","0178ac0c-da3b-002a-6a71-3b7a503aee5c","0178ac0c-da3a-0018-c3da-300537b37de3","0178ac0c-da3b-000a-8328-4978c7282b10","0178ac0c-da3b-001a-3cbf-712ec7c95d56","0178ac0c-da39-0006-666c-5e55443921a1","0178ac0c-da3a-001e-3823-31ace73bab0f","0178ac0c-da3b-0007-c118-137156a1e58e","0178ac0c-da3a-000b-fd39-13f6de576959","0178ac0c-da3c-0004-7a83-5f04f542811f","0178ac0c-da3b-0001-c08d-41b99bd84ea5","0178ac0c-da39-0003-70b5-38d170bdbc42","0178ac0c-da39-0008-059b-fd4c5492768d","0178ac0c-da3b-0000-f9ab-7894f8f0f24e","0178ac0c-da3c-0003-0824-fab9194a479d","0178ac0c-da3b-000c-0181-27e9878cb04e","0178ac0c-da3b-0021-0411-6e57115a3c5b","0178ac0c-da3a-0020-ab22-f222bfb4e8cf","0178ac0c-da3a-001a-d774-960c8ee1b620","0178ac0c-da3a-001b-f452-ea4ef277616f","0178ac0c-da3a-0015-32e9-d5f737539d01","0178ac0c-da3a-000a-9583-0ef277ac823a","0178ac0c-da3a-0012-f179-24ea07a32603","0178ac0c-da3b-0008-c880-7f2013ab26c7","0178ac0c-da3c-0001-4a56-6ea6f194d4a8","0178ac0c-da3b-0027-c3b8-1b2786d84b8e","0178ac0c-da3b-0029-8d9c-2e97b1d4e96b","0178ac0c-da3b-001f-3b32-265a348e0d6f","0178ac0c-da3a-0013-970d-b01fc1a4bb5a","0178ac0c-da3b-0011-0c21-d1bd96504728"],count:76,type:"events",average_conversion_time:15,median_conversion_time:15,breakdown:"",breakdown_value:""},{action_id:"$pageview",name:"$pageview",order:3,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"",breakdown_value:""},{action_id:"$pageview",name:"$pageview",order:4,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"",breakdown_value:""},{action_id:"$pageview",name:"$pageview",order:5,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"",breakdown_value:""},{action_id:"$pageview",name:"$pageview",order:6,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"",breakdown_value:""}],[{action_id:"$pageview",name:"$pageview",order:0,people:["0179e6d1-5d08-0001-b55c-70e41759f1f3","0178ac0c-d792-0017-90f0-5f0ccec9e378","0178ac0c-d792-0023-0129-ef955f1c73f0","0178ac0c-d792-0022-75f1-5b5bc6aa999a","0178ac0c-d792-0006-63d5-fac898a898f3","0178ac0c-d792-000d-b011-815dc106c87b","0178ac0c-d792-0005-29f4-c9d9c5848c69","0178ac0c-d792-0011-0bc5-e3b7b742e8e3","0178ac0c-d792-0002-7135-571fb4d744fb","0178ac0c-d792-0008-7b99-0a72df36d6b5","0178ac0c-d792-0020-e396-e7e7b54d017d","0178ac0c-d792-0016-372e-ddc392fb98b9"],count:12,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Firefox",breakdown_value:"Firefox"},{action_id:"$pageview",name:"$pageview",order:1,people:["0179e6d1-5d08-0001-b55c-70e41759f1f3","0178ac0c-d792-0017-90f0-5f0ccec9e378","0178ac0c-d792-0023-0129-ef955f1c73f0"],count:3,type:"events",average_conversion_time:24.333333333333332,median_conversion_time:30,breakdown:"Firefox",breakdown_value:"Firefox"},{action_id:"$pageview",name:"$pageview",order:2,people:["0179e6d1-5d08-0001-b55c-70e41759f1f3"],count:1,type:"events",average_conversion_time:11,median_conversion_time:11,breakdown:"Firefox",breakdown_value:"Firefox"},{action_id:"$pageview",name:"$pageview",order:3,people:["0179e6d1-5d08-0001-b55c-70e41759f1f3"],count:1,type:"events",average_conversion_time:1,median_conversion_time:1,breakdown:"Firefox",breakdown_value:"Firefox"},{action_id:"$pageview",name:"$pageview",order:4,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Firefox",breakdown_value:"Firefox"},{action_id:"$pageview",name:"$pageview",order:5,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Firefox",breakdown_value:"Firefox"},{action_id:"$pageview",name:"$pageview",order:6,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Firefox",breakdown_value:"Firefox"}],[{action_id:"$pageview",name:"$pageview",order:0,people:["01793986-b36c-0000-9f13-e902ff69ef1e","0179d27b-d8ce-0000-1a03-f04894a7e2e0","017aa0ce-49b9-0000-e148-50f3df4fd0eb","017b2b03-1492-0000-a66a-c71ea8fdbe3c","017be320-f782-0000-7759-8b3df3069639","0178ac0c-d792-0013-94e6-70d3da0445cd","017a2f37-b1e4-0000-7120-a0212c0d8d40","017a8752-9f6c-0003-bff9-3c843c507c7a","0178ac0c-d792-000f-82ca-5ffe0dace0c3","0178ac0c-d792-0007-58ad-b8cde85cf3cf","0178c69a-cca4-0000-63ff-45bb2246c3b6","0178ac0c-d792-0003-a081-4cab7e9387c4","0178ac0c-d792-000b-ce24-3e9293e183f0","017b845b-17e0-0000-3eca-9dd515574253","0178ac0c-d792-0014-b267-daf2bfb34d4c","017923c5-1176-0000-0c7b-627abd77280d","0178ac0c-d792-0025-031e-7c0d3edf794a","0178ac0c-effd-0000-635c-c665057e2d75","0178ac0c-d793-0000-7433-3fd4065a0fdd","0178ac0c-d792-001e-fdd2-e44bf453122a","017a8751-832c-0001-7db5-7fcd702198fe"],count:21,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Chrome",breakdown_value:"Chrome"},{action_id:"$pageview",name:"$pageview",order:1,people:["01793986-b36c-0000-9f13-e902ff69ef1e","0179d27b-d8ce-0000-1a03-f04894a7e2e0","017aa0ce-49b9-0000-e148-50f3df4fd0eb","017b2b03-1492-0000-a66a-c71ea8fdbe3c","017be320-f782-0000-7759-8b3df3069639","0178ac0c-d792-0013-94e6-70d3da0445cd","017a2f37-b1e4-0000-7120-a0212c0d8d40","017a8752-9f6c-0003-bff9-3c843c507c7a","0178ac0c-d792-000f-82ca-5ffe0dace0c3","0178ac0c-d792-0007-58ad-b8cde85cf3cf","0178c69a-cca4-0000-63ff-45bb2246c3b6","0178ac0c-d792-0003-a081-4cab7e9387c4","0178ac0c-d792-000b-ce24-3e9293e183f0","017b845b-17e0-0000-3eca-9dd515574253"],count:14,type:"events",average_conversion_time:47729.07653061225,median_conversion_time:30,breakdown:"Chrome",breakdown_value:"Chrome"},{action_id:"$pageview",name:"$pageview",order:2,people:["01793986-b36c-0000-9f13-e902ff69ef1e","0179d27b-d8ce-0000-1a03-f04894a7e2e0","017aa0ce-49b9-0000-e148-50f3df4fd0eb","017b2b03-1492-0000-a66a-c71ea8fdbe3c","017be320-f782-0000-7759-8b3df3069639","0178ac0c-d792-0013-94e6-70d3da0445cd","017a2f37-b1e4-0000-7120-a0212c0d8d40","017a8752-9f6c-0003-bff9-3c843c507c7a"],count:8,type:"events",average_conversion_time:12213.74107142857,median_conversion_time:22.5,breakdown:"Chrome",breakdown_value:"Chrome"},{action_id:"$pageview",name:"$pageview",order:3,people:["01793986-b36c-0000-9f13-e902ff69ef1e","0179d27b-d8ce-0000-1a03-f04894a7e2e0","017aa0ce-49b9-0000-e148-50f3df4fd0eb","017b2b03-1492-0000-a66a-c71ea8fdbe3c","017be320-f782-0000-7759-8b3df3069639"],count:5,type:"events",average_conversion_time:3843.7285714285717,median_conversion_time:13,breakdown:"Chrome",breakdown_value:"Chrome"},{action_id:"$pageview",name:"$pageview",order:4,people:["01793986-b36c-0000-9f13-e902ff69ef1e","0179d27b-d8ce-0000-1a03-f04894a7e2e0","017aa0ce-49b9-0000-e148-50f3df4fd0eb","017b2b03-1492-0000-a66a-c71ea8fdbe3c","017be320-f782-0000-7759-8b3df3069639"],count:5,type:"events",average_conversion_time:68221.47142857141,median_conversion_time:13,breakdown:"Chrome",breakdown_value:"Chrome"},{action_id:"$pageview",name:"$pageview",order:5,people:["01793986-b36c-0000-9f13-e902ff69ef1e","0179d27b-d8ce-0000-1a03-f04894a7e2e0","017aa0ce-49b9-0000-e148-50f3df4fd0eb"],count:3,type:"events",average_conversion_time:709.8452380952381,median_conversion_time:13,breakdown:"Chrome",breakdown_value:"Chrome"},{action_id:"$pageview",name:"$pageview",order:6,people:["01793986-b36c-0000-9f13-e902ff69ef1e","0179d27b-d8ce-0000-1a03-f04894a7e2e0","017aa0ce-49b9-0000-e148-50f3df4fd0eb"],count:3,type:"events",average_conversion_time:261162.1517857143,median_conversion_time:18,breakdown:"Chrome",breakdown_value:"Chrome"}],[{action_id:"$pageview",name:"$pageview",order:0,people:["0178ac0c-d791-0000-05b8-096d19bfea54","0178ac0c-d792-001b-cadd-f108aef4b8a7","0178ac0c-d792-001f-8794-53c5e919fb68","0178ac0c-d792-001c-9173-63bf0443186c","0178ac0c-d792-000a-2c7d-2724b59a1d1d","0178ac0c-d792-0012-ecee-ae5b3f40b770","0178ac0c-d792-001a-f7a7-ff6cc0b3cb32","0178ac0c-d792-0010-e675-ecc65b44ee76","0178ac0c-d792-0009-8c7b-8b4fdc5453fb","0178ac0c-d792-0000-2ef9-4b20544dcb87","0178ac0c-d792-000e-4e6c-3915b861191e","0178ac0c-d792-001d-7711-c737497a9c8f","0178ac0c-d792-0015-e12c-e61279114534","0178ac0c-d792-0004-806a-5856cba2e2b9","0178ac0c-d792-0024-14e5-d716fe04923c","0178ac0c-d792-0018-11ff-3c121c3ef2ba","0178ac0c-d792-0001-177c-2897009b0a3e","0178ac0c-d792-0019-920e-42fec69f59c2","0178ac0c-d792-0021-5f3c-322d31d57747","0178ac0c-d792-000c-f353-68bed552cc75"],count:20,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Safari",breakdown_value:"Safari"},{action_id:"$pageview",name:"$pageview",order:1,people:["0178ac0c-d791-0000-05b8-096d19bfea54","0178ac0c-d792-001b-cadd-f108aef4b8a7","0178ac0c-d792-001f-8794-53c5e919fb68"],count:3,type:"events",average_conversion_time:30,median_conversion_time:30,breakdown:"Safari",breakdown_value:"Safari"},{action_id:"$pageview",name:"$pageview",order:2,people:["0178ac0c-d791-0000-05b8-096d19bfea54"],count:1,type:"events",average_conversion_time:30,median_conversion_time:30,breakdown:"Safari",breakdown_value:"Safari"},{action_id:"$pageview",name:"$pageview",order:3,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Safari",breakdown_value:"Safari"},{action_id:"$pageview",name:"$pageview",order:4,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Safari",breakdown_value:"Safari"},{action_id:"$pageview",name:"$pageview",order:5,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Safari",breakdown_value:"Safari"},{action_id:"$pageview",name:"$pageview",order:6,people:[],count:0,type:"events",average_conversion_time:null,median_conversion_time:null,breakdown:"Safari",breakdown_value:"Safari"}]],last_refresh:"2021-09-14T16:21:30.584737Z",is_cached:true}
}

export const isStepsEmpty = (filters: FilterType): boolean =>
    [...(filters.actions || []), ...(filters.events || [])].length === 0

export const deepCleanFunnelExclusionEvents = (filters: FilterType): FunnelStepRangeEntityFilter[] | undefined => {
    if (!filters.exclusions) {
        return filters.exclusions
    }

    const lastIndex = Math.max((filters.events?.length || 0) + (filters.actions?.length || 0) - 1, 1)
    return filters.exclusions.map((event) => {
        const funnel_from_step = event.funnel_from_step ? clamp(event.funnel_from_step, 0, lastIndex - 1) : 0
        return {
            ...event,
            ...{ funnel_from_step },
            ...{
                funnel_to_step: event.funnel_to_step
                    ? clamp(event.funnel_to_step, funnel_from_step + 1, lastIndex)
                    : lastIndex,
            },
        }
    })
}

export const getClampedStepRangeFilter = ({
    stepRange,
    filters,
}: {
    stepRange?: FunnelStepRangeEntityFilter
    filters: FilterType
}): FunnelStepRangeEntityFilter => {
    const maxStepIndex = Math.max((filters.events?.length || 0) + (filters.actions?.length || 0) - 1, 1)
    const funnel_from_step = clamp(stepRange?.funnel_from_step ?? filters.funnel_from_step ?? 0, 0, maxStepIndex)
    return {
        ...(stepRange as FunnelStepRangeEntityFilter),
        funnel_from_step,
        funnel_to_step: clamp(
            stepRange?.funnel_to_step ?? filters.funnel_to_step ?? maxStepIndex,
            funnel_from_step + 1,
            maxStepIndex
        ),
    }
}
