// @ts-nocheck
import { clamp, compactNumber } from 'lib/utils'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { getChartColors } from 'lib/colors'
// import api from 'lib/api'
import {
    FilterType,
    FunnelExclusionEntityFilter,
    FunnelRequestParams,
    FunnelResult,
    FunnelStep,
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
                        '017b611a-36e9-0000-cde6-9b0c87e88291',
                        '017b0c18-4d52-0000-f0e7-ce60443296ec',
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
            ],
            [
                {
                    action_id: 'set email experiment variant',
                    name: 'set email experiment variant',
                    order: 0,
                    people: [
                        '017b5369-18ec-0000-80c7-3ffe1902911b',
                        '017b5282-0793-0000-8b6a-615342eb4ef9',
                        '017b538b-f7b1-0000-7a1d-c3996ee86ee0',
                        '017b4cf5-3647-0000-09da-5a469f4170db',
                        '017b5f9b-bbf3-0000-76e9-86f6ce402423',
                        '017b3de1-deb1-0000-7bdf-a119cab06477',
                        '017b50cc-654b-0000-aa08-de207b7605f6',
                        '017b59a3-de49-0000-ee34-2cbbc93e549f',
                        '017b4936-332f-0000-2044-daa908205e5c',
                        '017b5aa4-3852-0000-8ff6-f2edbe46e849',
                        '017b61ef-4a7b-0000-7748-612354685833',
                        '017b5451-fc00-0000-0a74-0ddb2595fd79',
                        '017b5b3d-c281-0000-e893-6451bd3da82a',
                        '017af891-6357-0000-b2b6-82be83bd120e',
                        '017b5d79-7e3d-0000-e9e1-80a9a588b75f',
                        '017b5f07-a524-0000-db09-060cd636b604',
                        '017b5ea1-502a-0000-9a91-aa3399a63b9b',
                        '017b4f7d-5e1e-0000-f80a-b7792d212d3d',
                        '017b63ef-512a-0000-527d-4988dee72d1c',
                        '017b5f1b-39e1-0000-f9a3-4f4d53027cd0',
                        '017b5fe4-3302-0000-b041-b39e24d73012',
                        '017b6218-59ac-0000-7f84-75a99de44cc2',
                        '017b602a-2877-0000-993a-e296006e6c88',
                        '017aa9ee-c062-0000-a135-bb8b31b60258',
                        '017b5f9d-e85e-0000-930f-140b2784aa92',
                        '017b5e91-8d3f-0000-d1f4-58e541e701bd',
                        '017b62a6-c4bb-0000-418a-7dd84a982b5e',
                        '017b525a-0eba-0000-bf99-dc0e7acd0fc1',
                        '017b401d-5f45-0000-768c-b0251615b538',
                        '017add03-65b0-0000-3c09-74207896c3b1',
                        '017b6195-4dda-0000-8fb6-12c8b1139610',
                        '017ac84f-4b53-0000-346b-1451403e400c',
                        '017b5373-5004-0000-7781-33c96f3d2165',
                        '017b5a05-c815-0000-0c20-69423d681868',
                        '017b53d4-8118-0000-b817-99f806062431',
                        '017b5287-58bd-0000-2b2c-a21334b8670b',
                        '017b5d45-cb50-0000-4daf-d4f1f3d6b38f',
                        '017640aa-c4af-0000-747d-a3e04926c06c',
                        '017b5f94-c6b6-0000-6096-c368725c7c27',
                        '017b6448-de50-0000-f0f2-9100d7b5bfa7',
                        '017b3e49-e2b5-0000-d3a4-fe05c7c65603',
                        '017b5358-30b9-0000-cb52-ef096cdd80dd',
                        '017b5be0-e25e-0000-1879-662127e4dcdb',
                        '017b6312-323f-0000-7b78-0a0898a4e64a',
                        '017b6153-efd7-0000-defe-41b185b9de63',
                        '017b5850-4836-0000-f370-72d2f33789b8',
                        '017b4938-08c3-0000-85ea-50bd7c58309e',
                        '017b5885-8d5d-0000-4cfe-4be44c8bf3e2',
                        '017b51b6-a48b-0000-c41c-94726c4cab85',
                        '017b5cb1-ab99-0000-1eb9-86c538ba0008',
                        '01790d6b-3229-0000-7d82-b3e6c1b76bd4',
                        '017b5171-f561-0000-e7a4-38c3a209c7db',
                        '017b6312-4bc6-0000-6b0c-f03734809229',
                        '017b5329-2cb3-0000-e8b3-2dac30973eb5',
                        '017b650d-2e52-0000-cf8b-ecf684f8ea18',
                        '017b3d97-0903-0000-eeda-97b27ac5787f',
                        '0176725d-ad46-0000-0325-327efec80dd2',
                        '017b5dd8-c6d2-0000-655d-027d718d3b54',
                        '017b5f39-acf4-0000-6213-0d126741bc0a',
                        '017b0ccd-5ed3-0000-c6e1-cba7757b03d9',
                        '017633ec-f311-0000-324e-3931dedd6ecd',
                        '017b5494-2116-0000-e339-55713409b0ee',
                        '017b5ff0-8be2-0000-30f7-1e03305b2590',
                        '017b56bf-4740-0000-4a23-6c13a6acb3bb',
                        '017b53d4-6ef6-0000-10ef-9dfc9a97f499',
                        '017b642b-7436-0000-5b67-7b59ae98a005',
                        '017b5d83-e145-0000-aa6c-ec5db2b5cc81',
                        '017b0a76-81da-0000-972f-84089b660dfc',
                        '017b4a58-8e0a-0000-60a2-4d1afb538f0d',
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
                    people: ['017b5369-18ec-0000-80c7-3ffe1902911b', '017b5282-0793-0000-8b6a-615342eb4ef9'],
                    count: 2,
                    type: 'events',
                    average_conversion_time: 164562.5,
                    median_conversion_time: 164562.5,
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
                        '017b46ee-8e39-0000-d256-1a6853781ed1',
                        '017b5f3f-1d2e-0000-316a-413f1a866106',
                        '017b6270-9200-0000-4e71-f49d4556d485',
                        '017b4f31-5d3d-0000-7857-bc7246f1ab32',
                        '017b52fc-f334-0000-9772-e01e3bb68e8c',
                        '017b5f93-6912-0000-8663-cb00a01546dc',
                        '017b4603-b5d0-0000-d82d-07de4f2963ea',
                        '017b402d-d7c8-0000-97b6-64948c71fa19',
                        '01797683-b0d3-0000-83a2-013f9517d601',
                        '017b534e-2e28-0000-7c92-be6267e0653a',
                        '017b56b7-befc-0000-9a3c-a0e14c6060b8',
                        '017b5713-ce12-0000-81df-b2c52060d032',
                        '017b4ac0-a8ff-0000-3224-669e34086dac',
                        '017b4eb4-2b7d-0000-654c-7f4be33b45bd',
                        '017b6517-560e-0000-6cac-e106f99851bc',
                        '017b5561-17f8-0000-3e7b-fd3cb238d196',
                        '017b6392-0fa3-0000-4f41-53b77d98f43a',
                        '017b519e-c193-0000-c586-aa811e1d73a6',
                        '017b5f61-a47c-0000-20f6-65b5689014a3',
                        '0179f4d0-e14d-0000-9270-40e5e829c117',
                        '017a1aa0-45df-0000-3ab3-8e972c85f02a',
                        '017b4eac-65de-0000-a0a5-aaeb35b125d6',
                        '017b402b-2ac6-0000-3dbe-2374bc6025ee',
                        '017b5f8a-5881-0000-62f8-d452409fa0af',
                        '017b5633-c444-0000-1189-b67c820aa56f',
                        '017b59a5-cd63-0000-c7ec-f803b92e4d6b',
                        '017a43bd-7645-0000-61d0-e8e84b7bccad',
                        '017b54c4-c8fd-0000-8d26-0bae507a03cb',
                        '017b238e-4f05-0000-65bd-c6f10b979c23',
                        '017b5f01-72a7-0000-7e96-91a22f9f7d45',
                        '017b5d89-8635-0000-670b-6465345d733e',
                        '017b5c31-a310-0000-ba05-0b1a5e0dc220',
                        '33b15212-6467-4324-8e2e-2ba8ac2b058c',
                        '017b62d4-dea4-0000-4ca8-78e339ad84b6',
                        '017b6280-9b55-0000-940c-3129d7b11477',
                        '017b3902-a9de-0000-c33a-2c3f9564b01f',
                        '017b61b2-0a1a-0000-e089-09e1729f9fae',
                        '017b6018-41ab-0000-3103-f52a760ad0d2',
                        '017b5f3f-5529-0000-28de-987ba33463c1',
                        '017b5a92-e4b9-0000-5635-f42ca766020d',
                        '017b5a98-8c1c-0000-1a18-5895f80bbeb6',
                        '017b622a-ae0b-0000-d9a6-12816b26b97e',
                        '017b4ed4-1866-0000-8bc1-a2a9923fd629',
                        '017b3d54-76c8-0000-b29e-3f7070d5ecb1',
                        '017b600d-741a-0000-840c-3e9ae83aed40',
                        '017b1c7a-744b-0000-3de0-28065aec358a',
                        '017b4ce8-d280-0000-3029-f5efdcab2570',
                        '017afb39-ab50-0000-114e-4d0f117d3ce1',
                        '017b3fbf-bde8-0000-33bc-8578e55303f6',
                        '017b596d-9048-0000-940f-18892cb7e8fe',
                        '017b4efd-c255-0000-d911-c97ad6dbdc88',
                        '017b6376-3378-0000-8523-91443bdf02cb',
                        '017b55a0-0ff6-0000-5857-a6fc17eda088',
                        '017b64fc-f16a-0000-d60e-40d1c8dfebbb',
                        '017b51ff-c119-0000-5aaa-8521990a4b61',
                        '017b5ef0-7e53-0000-14f0-bdccd0b5602c',
                        '017b3915-4d1a-0000-57a7-c2276dcf3da9',
                        '017b64a6-54b5-0000-57b0-b6b64cf4cc9e',
                        '017b6413-7d41-0000-a2d1-fc7ba15e49cf',
                        '017b48ae-7368-0000-66a5-bd4e531acfc4',
                        '017a0970-af29-0000-3c4a-030345a3c0cd',
                        '017b5a03-8f06-0000-c6a9-bbc2dcab344a',
                        '017b6542-0d1c-0000-e9a4-8e6c725255bd',
                        '017b59a9-295f-0000-8f53-3b21cb405e10',
                        '017b5396-30db-0000-d2f4-f5cc19bc5db7',
                        '017b4eb5-22e1-0000-2930-c2ba81822375',
                        '017b6066-3b62-0000-ec47-483aef47ac32',
                        '017b3cc5-9950-0000-44b7-5801904c894e',
                        '017b519a-b37a-0000-c685-2eb0abb400cb',
                        '017b5f49-c368-0000-398d-c28c20c637ef',
                        '017b4e82-b683-0000-cb84-fc0df6caf634',
                        '017ad4fa-5b3e-0000-aa09-96375ec51b4f',
                        '017b4e64-0ff6-0000-913c-45633e7fd013',
                        '017b54db-a0f5-0000-366a-0fe05cce28b2',
                        '017b607c-1dc3-0000-b63d-b9117f48efeb',
                        '017b4280-ebb8-0000-7984-4f8e7c69dbc8',
                        '017b6135-410d-0000-c119-b6ea56abde5a',
                        '017b5ee4-d16c-0000-a537-db4fd2b8c85f',
                        '017b518f-412a-0000-09ae-8126aa057c91',
                        '017b56e1-26fb-0000-720a-936a3535cc5c',
                        '017b523e-2a80-0000-597c-f9b305e1f3b3',
                        '017b5fe0-964b-0000-b75c-8624ee6f19fd',
                        '017b5ff8-ca17-0000-5361-f9ba6acb23f9',
                        '017b3fbf-958c-0000-cde8-9529ccd83701',
                        '017b5a04-892f-0000-148a-430e87729ddf',
                        '017819ed-3cec-0000-a75f-13a4c6af29f6',
                        '017af6c9-b2a1-0000-ebf9-c207cb96e697',
                        '017b5c16-c788-0000-d37b-7245e3c629b2',
                    ],
                    count: 88,
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
                        '017b46ee-8e39-0000-d256-1a6853781ed1',
                        '017b5f3f-1d2e-0000-316a-413f1a866106',
                        '017b6270-9200-0000-4e71-f49d4556d485',
                        '017b4f31-5d3d-0000-7857-bc7246f1ab32',
                        '017b52fc-f334-0000-9772-e01e3bb68e8c',
                        '017b5f93-6912-0000-8663-cb00a01546dc',
                        '017b4603-b5d0-0000-d82d-07de4f2963ea',
                        '017b402d-d7c8-0000-97b6-64948c71fa19',
                        '01797683-b0d3-0000-83a2-013f9517d601',
                        '017b534e-2e28-0000-7c92-be6267e0653a',
                        '017b56b7-befc-0000-9a3c-a0e14c6060b8',
                        '017b5713-ce12-0000-81df-b2c52060d032',
                        '017b4ac0-a8ff-0000-3224-669e34086dac',
                        '017b4eb4-2b7d-0000-654c-7f4be33b45bd',
                        '017b6517-560e-0000-6cac-e106f99851bc',
                        '017b5561-17f8-0000-3e7b-fd3cb238d196',
                        '017b6392-0fa3-0000-4f41-53b77d98f43a',
                    ],
                    count: 17,
                    type: 'events',
                    average_conversion_time: 279.05882352941177,
                    median_conversion_time: 56,
                    breakdown: 'email-gated-signup-control',
                    breakdown_value: 'email-gated-signup-control',
                },
            ],
            [
                {
                    action_id: 'set email experiment variant',
                    name: 'set email experiment variant',
                    order: 0,
                    people: [
                        '017b4e5a-1937-0000-9e3d-6c8903ba5a67',
                        '017b4511-a587-0000-7628-902582e572cb',
                        '017b3aab-a0a6-0000-b301-e9460c952f9c',
                        '017b50b9-fd0b-0000-436b-af69b6eb5b50',
                        '017b4054-7389-0000-df53-b29a8ad9e235',
                        '01799a9a-29cb-0000-ca25-08bf4a018dbc',
                        '017af315-4618-0000-eb0f-e10cf8da7ed4',
                        '017b4f34-4387-0000-2555-3b09a9c969b3',
                        '017b4f0d-cb13-0000-6872-8293dfc97191',
                        '017b45e6-cadc-0000-8045-d3f1c3ef2ce8',
                        '017b4396-4301-0000-29d4-2e9b2310d716',
                        '01763a02-36cc-0000-765b-dff9ecb716fc',
                        '017b0c6d-648c-0000-4007-ecb854db6a86',
                        '017b49de-4619-0000-e55f-3dad3f6503f8',
                        '017b4000-a984-0000-06a2-8cb0a12db903',
                        '017b4ec1-43fd-0000-ca73-c9faaeb4f312',
                        '017b3f0e-224e-0000-a1ba-42f1c10d5751',
                        '017aed57-f11f-0000-bdb5-f67f8a81a042',
                        '017b4ec7-0884-0000-3fd1-c23f63b9b9fc',
                    ],
                    count: 19,
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
                    people: [],
                    count: 0,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
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
                        '0179ad22-f17a-0000-8035-67eb216388b7',
                        '017b5f93-d6e7-0000-d508-d74848c831f8',
                        '017b5f57-b312-0000-6db9-2ad6741718c1',
                        '017b533e-0911-0000-e599-27d0b1fab56a',
                        '017b4584-1dde-0000-66df-3225f233dead',
                        '017b4dc5-d9db-0000-e9c5-f5ab0ca6674e',
                        '017b5f22-f82a-0000-75af-f0b6c0dca3aa',
                        '017b3fbf-dc51-0000-22b0-8534adc59087',
                        '017b5b34-42f8-0000-d7b0-34d478b3e1e7',
                        '017b5a72-c9c3-0000-9ba2-0f800035d8ee',
                        '0177f701-f314-0001-85cb-9be50a57fdae',
                        '017b57a3-153f-0000-01f8-094557b790b6',
                        '017b62df-6ef4-0000-8e68-009910699acf',
                        '017b59ad-c736-0000-5dcf-c12410192a0e',
                        '017b623c-f998-0000-221a-7adc2b0c1651',
                        '017b440b-8a8c-0000-0e3b-c5fcf7a81f4d',
                        '017b50e0-7077-0000-5e52-25f6a9777db4',
                        '017b5f1c-0190-0000-5626-aee4b71e7532',
                        '017b5f11-187a-0000-6ae3-36c52f2e7271',
                        '017b6185-5696-0000-2ebe-ded08667961f',
                        '017b656b-8335-0000-7404-672e63a6bca3',
                        '017b62c2-2088-0000-7e5d-c184236a6503',
                        '017b50c8-ab5f-0000-297d-2c9e921a064d',
                        '017ad1d8-7bfc-0000-cbc5-db3f17e0072e',
                        '017aed4d-d70f-0000-d1b9-79760b02763e',
                        '017b606c-09a9-0000-b7fd-e13cff8dd386',
                        '017845c1-0eae-0000-cfc6-d33a6bbc136b',
                        '017b6028-3bad-0000-9fd5-a6652140fb81',
                        '017a9c14-852d-0000-bf79-e1ed0bfbab39',
                        '017b6089-8db9-0000-8d25-c44cb4c5f631',
                        '017b605f-eed9-0000-9933-59f9bb5253e6',
                        '017b4363-f953-0000-7e9d-3b875eaca21d',
                        '017b42bf-c565-0000-3684-f2579ceb0d98',
                        '2b40d9b6-5563-49ec-afe3-2529a4986fd9',
                        '017b3a4a-096a-0000-9de8-c4b96851318d',
                        '017b5ef2-91a9-0000-d8c5-25cfaa3fd536',
                        '017b5f55-5d03-0000-1fbe-c6c25d29dda8',
                        '017b5fde-0b5a-0000-6343-2894cf879d8a',
                    ],
                    count: 38,
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
                    people: [],
                    count: 0,
                    type: 'events',
                    average_conversion_time: null,
                    median_conversion_time: null,
                    breakdown: 'email-gated-signup-not-skippable',
                    breakdown_value: 'email-gated-signup-not-skippable',
                },
            ],
        ],
        type: 'Funnel',
        last_refresh: '2021-08-20T22:21:18.062712Z',
        is_cached: true,
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
