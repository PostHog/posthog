import { uuid } from 'lib/utils/dom'
import { UnexpectedNeverError } from 'lib/utils/guards'
import { genericOperatorMap } from 'lib/utils/operators'

import {
    CustomChannelCondition,
    CustomChannelField,
    CustomChannelOperator,
    CustomChannelRule,
} from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyOperator } from '~/types'

export const combinerOptions = [
    { label: 'All', value: FilterLogicalOperator.And },
    { label: 'Any', value: FilterLogicalOperator.Or },
]

export const keyOptions = [
    {
        label: 'Referring domain',
        value: CustomChannelField.ReferringDomain,
    },
    {
        label: 'UTM Source',
        value: CustomChannelField.UTMSource,
    },
    {
        label: 'UTM Medium',
        value: CustomChannelField.UTMMedium,
    },
    {
        label: 'UTM Campaign',
        value: CustomChannelField.UTMCampaign,
    },
    {
        label: 'URL',
        value: CustomChannelField.URL,
    },
    {
        label: 'Hostname',
        value: CustomChannelField.Hostname,
    },
    {
        label: 'Pathname',
        value: CustomChannelField.Pathname,
    },
]

export const opOptions = Object.values(CustomChannelOperator).map((op) => {
    return {
        label: genericOperatorMap[op],
        value: op,
    }
})

export const isNullary = (operator: CustomChannelOperator): boolean => {
    return [CustomChannelOperator.IsSet, CustomChannelOperator.IsNotSet].includes(operator)
}

export const opToPropertyOperator: Record<CustomChannelOperator, PropertyOperator> = {
    [CustomChannelOperator.Exact]: PropertyOperator.Exact,
    [CustomChannelOperator.IsNot]: PropertyOperator.IsNot,
    [CustomChannelOperator.IsSet]: PropertyOperator.IsSet,
    [CustomChannelOperator.IsNotSet]: PropertyOperator.IsNotSet,
    [CustomChannelOperator.IContains]: PropertyOperator.IContains,
    [CustomChannelOperator.NotIContains]: PropertyOperator.NotIContains,
    [CustomChannelOperator.Regex]: PropertyOperator.Regex,
    [CustomChannelOperator.NotRegex]: PropertyOperator.NotRegex,
}

export function keyToSessionProperty(key: CustomChannelField): string {
    switch (key) {
        case CustomChannelField.ReferringDomain:
            return '$entry_referring_domain'
        case CustomChannelField.UTMSource:
            return '$entry_utm_source'
        case CustomChannelField.UTMMedium:
            return '$entry_utm_medium'
        case CustomChannelField.UTMCampaign:
            return '$entry_utm_campaign'
        case CustomChannelField.URL:
            return '$entry_url'
        case CustomChannelField.Hostname:
            return '$entry_hostname'
        case CustomChannelField.Pathname:
            return '$entry_pathname'
        default:
            throw new UnexpectedNeverError(key)
    }
}

export function createNewChannelTypeRule(): CustomChannelRule {
    return {
        id: uuid(),
        items: [
            {
                id: uuid(),
                key: CustomChannelField.ReferringDomain,
                op: CustomChannelOperator.Exact,
                value: [],
            },
        ],
        channel_type: '',
        combiner: FilterLogicalOperator.And,
    }
}

export function createNewChannelTypeCondition(): CustomChannelCondition {
    return {
        id: uuid(),
        key: CustomChannelField.ReferringDomain,
        op: CustomChannelOperator.Exact,
        value: [],
    }
}
