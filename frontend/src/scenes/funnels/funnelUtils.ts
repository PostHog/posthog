// @ts-nocheck
import { clamp, compactNumber, humanFriendlyDuration } from 'lib/utils'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { getChartColors } from 'lib/colors'
// import api from 'lib/api'
import {
    FilterType,
    FunnelExclusionEntityFilter,
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
    // // Tricky: This API endpoint has wildly different return types depending on parameters.
    // const { refresh, ...bodyParams } = apiParams
    // let result = await api.create('api/insight/funnel/?' + (refresh ? 'refresh=true' : ''), bodyParams)
    // const start = window.performance.now()
    // while (result.result.loading && (window.performance.now() - start) / 1000 < SECONDS_TO_POLL) {
    //     await wait()
    //     result = await api.create('api/insight/funnel', bodyParams)
    // }
    // // if endpoint is still loading after 3 minutes just return default
    // if (result.loading) {
    //     throw { status: 0, statusText: 'Funnel timeout' }
    // }
    // return result
    console.log('api', apiParams)

    return {
        result: [
            [
                {
                    action_id: 'set email experiment variant',
                    name: 'set email experiment variant',
                    order: 0,
                    people: [
                        '017b7855-d26c-0000-36b6-fda7d7078d9a',
                        '017b77f8-a0b6-0000-ea07-6bdad3e41413',
                        '017b0c5b-c4cb-0000-e889-4448d5ba97b1',
                    ],
                    count: 3,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: '',
                    breakdown_value: '',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 1,
                    people: [],
                    count: 0,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: '',
                    breakdown_value: '',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 2,
                    people: [],
                    count: 0,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: '',
                    breakdown_value: '',
                },
            ],
            [
                {
                    action_id: 'set email experiment variant',
                    name: 'set email experiment variant',
                    order: 0,
                    people: [
                        '017b7b01-860a-0000-6e69-91a0dacc3c54',
                        '017b770b-2214-0000-16a4-7884626f0379',
                        '017b5f9b-bbf3-0000-76e9-86f6ce402423',
                        '017b4d0e-facb-0000-420c-9eeee48520ce',
                        '017b59a3-de49-0000-ee34-2cbbc93e549f',
                        '017b5aa4-3852-0000-8ff6-f2edbe46e849',
                        '017b61ef-4a7b-0000-7748-612354685833',
                        '017b5b3d-c281-0000-e893-6451bd3da82a',
                        '017b72bb-7a8f-0000-c5a2-13fa6f533b33',
                        '017b727b-15c9-0000-7dd1-509d2d25f865',
                        '017b77a8-0dd7-0000-4311-54a4debbdd90',
                        '017b5d79-7e3d-0000-e9e1-80a9a588b75f',
                        '017b5f07-a524-0000-db09-060cd636b604',
                        '017b5ea1-502a-0000-9a91-aa3399a63b9b',
                        '017b72cb-2f87-0000-961e-3f59ddb3a674',
                        '017b63ef-512a-0000-527d-4988dee72d1c',
                        '017b5f1b-39e1-0000-f9a3-4f4d53027cd0',
                        '017b5fe4-3302-0000-b041-b39e24d73012',
                        '017b7295-03a1-0000-893a-177d32d782ba',
                        '017b6218-59ac-0000-7f84-75a99de44cc2',
                        '017b602a-2877-0000-993a-e296006e6c88',
                        '017b5f9d-e85e-0000-930f-140b2784aa92',
                        '017b5e91-8d3f-0000-d1f4-58e541e701bd',
                        '017b62a6-c4bb-0000-418a-7dd84a982b5e',
                        '017b79b1-eb5d-0000-7983-7217fcf1e3e0',
                        '017b6e4a-0bdb-0000-7e8b-b3d8259c49ab',
                        '017b68cf-931b-0000-3b1e-a6d29ca23993',
                        '017b6757-a024-0000-24f2-a1356a29ee21',
                        '017b6902-fc2a-0000-ac66-525afcd3738d',
                        '017b63c8-2cce-0000-7a52-2f5f99d13c9a',
                        '017b6195-4dda-0000-8fb6-12c8b1139610',
                        '017b5a05-c815-0000-0c20-69423d681868',
                        '017b5d45-cb50-0000-4daf-d4f1f3d6b38f',
                        '017b3203-d7c7-0000-9a9c-d46fdc0bcead',
                        '017b7982-3ac0-0000-bf42-519163774cd8',
                        '017640aa-c4af-0000-747d-a3e04926c06c',
                        '017b5f94-c6b6-0000-6096-c368725c7c27',
                        '017b6448-de50-0000-f0f2-9100d7b5bfa7',
                        '017b5be0-e25e-0000-1879-662127e4dcdb',
                        '017b6312-323f-0000-7b78-0a0898a4e64a',
                        '017b79ae-f232-0000-adb3-c12830bbea10',
                        '017b6153-efd7-0000-defe-41b185b9de63',
                        '017b5850-4836-0000-f370-72d2f33789b8',
                        '017b77dc-2491-0000-ca09-04f15e5855ba',
                        '017b5885-8d5d-0000-4cfe-4be44c8bf3e2',
                        '017b5cb1-ab99-0000-1eb9-86c538ba0008',
                        '017b7913-6a5b-0000-342f-6f807441a17d',
                        '01790d6b-3229-0000-7d82-b3e6c1b76bd4',
                        '017b7590-955b-0000-ccdf-d289f4018dee',
                        '017b78d5-374a-0000-bd6a-c2bac0a60c9f',
                        '017b6312-4bc6-0000-6b0c-f03734809229',
                        '017b650d-2e52-0000-cf8b-ecf684f8ea18',
                        '017b6d7b-c2f5-0000-1a46-bf2dc179b02f',
                        '017ac9d8-61b4-0000-855f-b14a858c7c88',
                        '017b76b2-fdd6-0000-049d-f995c6b866c4',
                        '017b7381-d762-0000-199f-0a7216bd3407',
                        '017b79bb-e5c5-0000-e5f8-6edffac32ccb',
                        '0176725d-ad46-0000-0325-327efec80dd2',
                        '017b5dd8-c6d2-0000-655d-027d718d3b54',
                        '017b5f39-acf4-0000-6213-0d126741bc0a',
                        '017633ec-f311-0000-324e-3931dedd6ecd',
                        '017b7619-446d-0000-7821-28b9f1579e45',
                        '017b5ff0-8be2-0000-30f7-1e03305b2590',
                        '017b6a03-af1c-0000-ee00-9d09260c86bb',
                        '017b56bf-4740-0000-4a23-6c13a6acb3bb',
                        '017a3503-42c2-0000-3654-31b59409833c',
                        '017b794f-82f4-0000-3635-0dd7096166e3',
                        '017b642b-7436-0000-5b67-7b59ae98a005',
                        '017b5d83-e145-0000-aa6c-ec5db2b5cc81',
                        '017b5f26-ffd9-0000-ac12-da99b1f778f2',
                        '017b5b86-5e27-0000-3059-dc1fa5b01c21',
                        '017b2b27-d356-0000-9087-4c4a3ad04ecf',
                    ],
                    count: 72,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: 'email-gated-signup-skippable',
                    breakdown_value: 'email-gated-signup-skippable',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 1,
                    people: ['017b7b01-860a-0000-6e69-91a0dacc3c54', '017b770b-2214-0000-16a4-7884626f0379'],
                    count: 2,
                    type: 'events',
                    average_conversion_time: 72180,
                    median_conversion_time: 72180,
                    breakdown: 'email-gated-signup-skippable',
                    breakdown_value: 'email-gated-signup-skippable',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 2,
                    people: ['017b7b01-860a-0000-6e69-91a0dacc3c54'],
                    count: 1,
                    type: 'events',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    breakdown: 'email-gated-signup-skippable',
                    breakdown_value: 'email-gated-signup-skippable',
                },
            ],
            [
                {
                    action_id: 'set email experiment variant',
                    name: 'set email experiment variant',
                    order: 0,
                    people: [
                        '017b6517-560e-0000-6cac-e106f99851bc',
                        '017b6392-0fa3-0000-4f41-53b77d98f43a',
                        '017b5f93-6912-0000-8663-cb00a01546dc',
                        '017b76a2-0fc0-0001-69c3-ade5846d9aad',
                        '017b56b7-befc-0000-9a3c-a0e14c6060b8',
                        '017b7195-27fb-0000-b63c-e4d799c4cc6f',
                        '017b5713-ce12-0000-81df-b2c52060d032',
                        '017b6270-9200-0000-4e71-f49d4556d485',
                        '017b67a3-66e9-0000-1084-450bae970199',
                        '017b5f3f-1d2e-0000-316a-413f1a866106',
                        '017b7862-987c-0000-08b7-85ca1e766eee',
                        '017b78d9-cb37-0000-fe6a-c8dddb9a8de7',
                        '017b7a8c-2c7c-0000-530b-64d992124aaf',
                        '017b5f61-a47c-0000-20f6-65b5689014a3',
                        '017b6f53-ce6e-0000-e2ed-d47fb03d6625',
                        '0179f4d0-e14d-0000-9270-40e5e829c117',
                        '017a1aa0-45df-0000-3ab3-8e972c85f02a',
                        '017b4eac-65de-0000-a0a5-aaeb35b125d6',
                        '017b777e-2bed-0000-1f39-fd7edf4a3382',
                        '017b6dda-aad4-0000-91a5-b5526f937dba',
                        '017b5f8a-5881-0000-62f8-d452409fa0af',
                        '017b59a5-cd63-0000-c7ec-f803b92e4d6b',
                        '017a43bd-7645-0000-61d0-e8e84b7bccad',
                        '017b238e-4f05-0000-65bd-c6f10b979c23',
                        '01798787-c43c-0000-bd31-bef0b15af0dc',
                        '017b5f01-72a7-0000-7e96-91a22f9f7d45',
                        '017b5d89-8635-0000-670b-6465345d733e',
                        '017b5c31-a310-0000-ba05-0b1a5e0dc220',
                        '017b6280-9b55-0000-940c-3129d7b11477',
                        '0177aa29-3ff6-0000-e47f-78b44dc18956',
                        '017b62d4-dea4-0000-4ca8-78e339ad84b6',
                        '017b61b2-0a1a-0000-e089-09e1729f9fae',
                        '017b6018-41ab-0000-3103-f52a760ad0d2',
                        '017b5f3f-5529-0000-28de-987ba33463c1',
                        '017b5a92-e4b9-0000-5635-f42ca766020d',
                        '017b5a98-8c1c-0000-1a18-5895f80bbeb6',
                        '017b622a-ae0b-0000-d9a6-12816b26b97e',
                        '017b6a59-5e26-0000-9518-de3375287b4e',
                        '017b7415-f340-0000-585d-831ec078b345',
                        '017b4f88-6a72-0000-cbf0-39be3c3727a9',
                        '017b600d-741a-0000-840c-3e9ae83aed40',
                        '017b1c7a-744b-0000-3de0-28065aec358a',
                        '0177161e-6648-0000-8e1b-508c1ee35f6a',
                        '017b73e0-1dc3-0000-a9cf-83394ece4fbd',
                        '017889d9-d860-0000-cda3-616246573b22',
                        '017b4ce8-d280-0000-3029-f5efdcab2570',
                        '017afb39-ab50-0000-114e-4d0f117d3ce1',
                        '017b722d-f0f2-0000-be48-c78d9c457fa5',
                        '017b596d-9048-0000-940f-18892cb7e8fe',
                        '017b6376-3378-0000-8523-91443bdf02cb',
                        '017b7af2-010e-0000-0111-a338658ef69a',
                        '017b7137-8f64-0000-fd91-a8bc486e2904',
                        '017b64fc-f16a-0000-d60e-40d1c8dfebbb',
                        '017b7412-be37-0000-01e3-13760eef3fc1',
                        '017b7414-7e15-0000-6fd4-7651670bcd7a',
                        '017b5ef0-7e53-0000-14f0-bdccd0b5602c',
                        '017b7877-e6cf-0000-8192-34de65701095',
                        '017b611a-36e9-0000-cde6-9b0c87e88291',
                        '017b6957-a2af-0000-e986-0a5776aa962a',
                        '017b6413-7d41-0000-a2d1-fc7ba15e49cf',
                        '017b64a6-54b5-0000-57b0-b6b64cf4cc9e',
                        '017a0970-af29-0000-3c4a-030345a3c0cd',
                        '017b5a03-8f06-0000-c6a9-bbc2dcab344a',
                        '017b6542-0d1c-0000-e9a4-8e6c725255bd',
                        '017b59a9-295f-0000-8f53-3b21cb405e10',
                        '017b667f-8d2d-0000-bc39-761cb586a1e7',
                        '017b7484-3a3f-0000-2ccc-3ba9f809cddc',
                        '017b62c6-bf4c-0000-4837-34efb1182868',
                        '017b7286-e9f1-0000-2097-1fea8d6d94fc',
                        '017b6066-3b62-0000-ec47-483aef47ac32',
                        '017b3cc5-9950-0000-44b7-5801904c894e',
                        '017b5f49-c368-0000-398d-c28c20c637ef',
                        '017b6810-0232-0000-bdb8-c5eca0fe10b9',
                        '017b670e-e298-0000-5ae8-a20c4d60acab',
                        '017b54db-a0f5-0000-366a-0fe05cce28b2',
                        '017b607c-1dc3-0000-b63d-b9117f48efeb',
                        '017b4280-ebb8-0000-7984-4f8e7c69dbc8',
                        '017b6135-410d-0000-c119-b6ea56abde5a',
                        '017b630a-1631-0000-b08f-d345b0b7da3a',
                        '017b5ee4-d16c-0000-a537-db4fd2b8c85f',
                        '017b56e1-26fb-0000-720a-936a3535cc5c',
                        '017b5fe0-964b-0000-b75c-8624ee6f19fd',
                        '017b7200-3425-0000-76ee-a099190cddb6',
                        '017b72ad-7e71-0000-b0ec-2f755100d629',
                        '017b6bdf-54ad-0000-74d1-c3efede231b0',
                        '017b5ff8-ca17-0000-5361-f9ba6acb23f9',
                        '017b5a04-892f-0000-148a-430e87729ddf',
                        '017819ed-3cec-0000-a75f-13a4c6af29f6',
                        '0179a028-972b-0000-5320-ece529b2b351',
                        '017b7280-c847-0000-eedb-0cf80d6eb874',
                        '017b7252-0e16-0000-c021-af684870f025',
                        '017b5c16-c788-0000-d37b-7245e3c629b2',
                    ],
                    count: 92,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: 'email-gated-signup-control',
                    breakdown_value: 'email-gated-signup-control',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 1,
                    people: [
                        '017b6517-560e-0000-6cac-e106f99851bc',
                        '017b6392-0fa3-0000-4f41-53b77d98f43a',
                        '017b5f93-6912-0000-8663-cb00a01546dc',
                        '017b76a2-0fc0-0001-69c3-ade5846d9aad',
                        '017b56b7-befc-0000-9a3c-a0e14c6060b8',
                        '017b7195-27fb-0000-b63c-e4d799c4cc6f',
                        '017b5713-ce12-0000-81df-b2c52060d032',
                        '017b6270-9200-0000-4e71-f49d4556d485',
                        '017b67a3-66e9-0000-1084-450bae970199',
                        '017b5f3f-1d2e-0000-316a-413f1a866106',
                        '017b7862-987c-0000-08b7-85ca1e766eee',
                    ],
                    count: 11,
                    type: 'events',
                    average_conversion_time: 16682,
                    median_conversion_time: 89,
                    breakdown: 'email-gated-signup-control',
                    breakdown_value: 'email-gated-signup-control',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 2,
                    people: [
                        '017b6517-560e-0000-6cac-e106f99851bc',
                        '017b6392-0fa3-0000-4f41-53b77d98f43a',
                        '017b5f93-6912-0000-8663-cb00a01546dc',
                        '017b76a2-0fc0-0001-69c3-ade5846d9aad',
                    ],
                    count: 4,
                    type: 'events',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    breakdown: 'email-gated-signup-control',
                    breakdown_value: 'email-gated-signup-control',
                },
            ],
            [
                {
                    action_id: 'set email experiment variant',
                    name: 'set email experiment variant',
                    order: 0,
                    people: ['017b6e8f-4aeb-0000-e26b-389338f9d04f', '01799a9a-29cb-0000-ca25-08bf4a018dbc'],
                    count: 2,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: 'email-gated-signup-old-flow',
                    breakdown_value: 'email-gated-signup-old-flow',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 1,
                    people: ['017b6e8f-4aeb-0000-e26b-389338f9d04f'],
                    count: 1,
                    type: 'events',
                    average_conversion_time: 43,
                    median_conversion_time: 43,
                    breakdown: 'email-gated-signup-old-flow',
                    breakdown_value: 'email-gated-signup-old-flow',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 2,
                    people: ['017b6e8f-4aeb-0000-e26b-389338f9d04f'],
                    count: 1,
                    type: 'events',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    breakdown: 'email-gated-signup-old-flow',
                    breakdown_value: 'email-gated-signup-old-flow',
                },
            ],
            [
                {
                    action_id: 'set email experiment variant',
                    name: 'set email experiment variant',
                    order: 0,
                    people: [
                        '017b77bd-58d8-0000-7bf8-e21ca435ea32',
                        '017b7772-98b1-0000-dfc3-c12314b1280a',
                        '017b6040-ddf6-0000-6c30-e395e6f7b316',
                        '017b5f93-d6e7-0000-d508-d74848c831f8',
                        '017b7838-e1df-0000-e8b2-7c0c3b71c0f5',
                        '017b7464-10b1-0000-cb07-ab4f7ff13c5e',
                        '017b78a2-1786-0000-3151-81ee531a6615',
                        '017b533e-0911-0000-e599-27d0b1fab56a',
                        '017b5f57-b312-0000-6db9-2ad6741718c1',
                        '017b79c4-08b6-0000-6c74-d36c5ae2817e',
                        '017b7279-f223-0000-cdea-e82b0c958dda',
                        '017b6612-3a4a-0000-5e98-b2831fd315a6',
                        '017b5f22-f82a-0000-75af-f0b6c0dca3aa',
                        '017b697a-dc9d-0000-7490-aae225f4f624',
                        '017b5b34-42f8-0000-d7b0-34d478b3e1e7',
                        '017b5a72-c9c3-0000-9ba2-0f800035d8ee',
                        '0177f701-f314-0001-85cb-9be50a57fdae',
                        '017b57a3-153f-0000-01f8-094557b790b6',
                        '017b74e7-6507-0000-6807-b9185bfe83e0',
                        '017b77b4-b2a9-0000-0563-5aafc1687eed',
                        '017b6f82-99df-0000-809c-bc872ca12a51',
                        '017b62df-6ef4-0000-8e68-009910699acf',
                        '017b7852-e03c-0000-5203-f27d8edb5ae7',
                        '017b59ad-c736-0000-5dcf-c12410192a0e',
                        '017b70ab-51c5-0000-d72c-1ff10924f3c8',
                        '017b6fa3-da90-0000-79e7-f7405f3e5962',
                        '017b623c-f998-0000-221a-7adc2b0c1651',
                        '017b708e-8df1-0000-5dcd-03ac91f3f10a',
                        '017b5f1c-0190-0000-5626-aee4b71e7532',
                        '017b7326-7be4-0000-2a30-e77ec676e546',
                        '017b788b-65c1-0000-75cc-fe634532992a',
                        '017729c3-1804-0000-5343-129b5917bb82',
                        '017b5f11-187a-0000-6ae3-36c52f2e7271',
                        '017b706a-f586-0000-ed7b-7b226303f5c4',
                        '017b6185-5696-0000-2ebe-ded08667961f',
                        '017b656b-8335-0000-7404-672e63a6bca3',
                        '017b74cf-d6b8-0000-9ce1-208792b8dbf3',
                        '017b6da8-7928-0000-ee4d-137e2086cae3',
                        '017b62c2-2088-0000-7e5d-c184236a6503',
                        '017ad1d8-7bfc-0000-cbc5-db3f17e0072e',
                        '0179e9db-4f39-0000-d2ac-58a3774e4553',
                        '017ad4ca-0c80-0000-7f65-61c249f7be7b',
                        '017b6b6e-5a72-0000-7f78-c043ccd631be',
                        '017a65e5-284c-0000-492c-ad7356a235bb',
                        '017b606c-09a9-0000-b7fd-e13cff8dd386',
                        '01790e80-6e27-0000-7fac-b20f8cfbc42e',
                        '017b6028-3bad-0000-9fd5-a6652140fb81',
                        '017aef26-225f-0000-2e83-ab30698aa359',
                        '017b737b-f5a6-0000-c995-2c9eee7f7379',
                        '017b6089-8db9-0000-8d25-c44cb4c5f631',
                        '017b605f-eed9-0000-9933-59f9bb5253e6',
                        '017b7492-1de1-0000-fc14-db92e20407cf',
                        '017b682f-2387-0000-bf63-b2b8e546b2ac',
                        '017b7560-4510-0000-117b-4f4a3d097f75',
                        '01787b08-e057-0000-695b-b104622949d1',
                        '2b40d9b6-5563-49ec-afe3-2529a4986fd9',
                        '017b5ef2-91a9-0000-d8c5-25cfaa3fd536',
                        '017b722b-8424-0000-676d-838025452d1b',
                        '017b770d-3316-0000-0ff6-1c6200f89c00',
                        '017b710e-6787-0000-f1ed-66b762aca8f1',
                        '017b5f55-5d03-0000-1fbe-c6c25d29dda8',
                        '017b5fde-0b5a-0000-6343-2894cf879d8a',
                    ],
                    count: 62,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: 'email-gated-signup-not-skippable',
                    breakdown_value: 'email-gated-signup-not-skippable',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 1,
                    people: ['017b77bd-58d8-0000-7bf8-e21ca435ea32'],
                    count: 1,
                    type: 'events',
                    average_conversion_time: 2838,
                    median_conversion_time: 2838,
                    breakdown: 'email-gated-signup-not-skippable',
                    breakdown_value: 'email-gated-signup-not-skippable',
                },
                {
                    action_id: 'user signed up',
                    name: 'user signed up',
                    order: 2,
                    people: ['017b77bd-58d8-0000-7bf8-e21ca435ea32'],
                    count: 1,
                    type: 'events',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    breakdown: 'email-gated-signup-not-skippable',
                    breakdown_value: 'email-gated-signup-not-skippable',
                },
            ],
        ],
        last_refresh: '2021-08-25T03:14:54.193941Z',
        is_cached: false,
    }
}

export const isStepsEmpty = (filters: FilterType): boolean =>
    [...(filters.actions || []), ...(filters.events || [])].length === 0

export const deepCleanFunnelExclusionEvents = (filters: FilterType): FunnelExclusionEntityFilter[] | undefined => {
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

export const getClampedExclusionFilter = (
    event: FunnelExclusionEntityFilter,
    filters: FilterType
): FunnelExclusionEntityFilter => {
    const maxStepIndex = Math.max((filters.events?.length || 0) + (filters.actions?.length || 0) - 1, 1)
    const funnel_from_step = clamp(event.funnel_from_step, 0, maxStepIndex)
    return {
        ...event,
        funnel_from_step,
        funnel_to_step: clamp(event.funnel_to_step, funnel_from_step + 1, maxStepIndex),
    }
}
