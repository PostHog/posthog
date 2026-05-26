import { connect, kea, key, path, props, selectors } from 'kea'
import { combineUrl } from 'kea-router'

import {
    SimpleOption,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { projectLogic } from 'scenes/projectLogic'

import type { apmTaxonomicGroupsLogicType } from './apmTaxonomicGroupsLogicType'

export const apmTaxonomicGroupsLogic = kea<apmTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'apmTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    selectors({
        endpointFilters: [
            () => [(_, props) => props.endpointFilters],
            (endpointFilters: Record<string, any>) => endpointFilters,
        ],
        apmTaxonomicGroups: [
            (s) => [s.currentProjectId, s.endpointFilters],
            (projectId, endpointFilters: Record<string, any> | undefined): TaxonomicFilterGroup[] => [
                {
                    name: 'Logs',
                    searchPlaceholder: 'logs',
                    type: TaxonomicFilterGroupType.Logs,
                    options: [
                        { key: 'message', name: 'message', propertyFilterType: 'log' },
                        { key: 'severity_level', name: 'severity_level', propertyFilterType: 'log' },
                        { key: 'trace_id', name: 'trace_id', propertyFilterType: 'log' },
                        { key: 'span_id', name: 'span_id', propertyFilterType: 'log' },
                    ],
                    localItemsSearch: (items: any[], q: string): any[] => {
                        if (!q) {
                            return items
                        }
                        return [
                            {
                                key: 'message',
                                name: 'Search log message for "' + q + '"',
                                value: q,
                                propertyFilterType: 'log',
                            },
                        ].concat(items.filter((item) => item.name?.toLowerCase().includes(q.toLowerCase())))
                    },
                    getName: (option: { key: string; name: string }) => option.name,
                    getValue: (option: { key: string; name: string }) => option.key,
                    getPopoverHeader: () => 'Log attributes',
                },
                {
                    name: 'Log attributes',
                    searchPlaceholder: 'attributes',
                    type: TaxonomicFilterGroupType.LogAttributes,
                    endpoint: combineUrl(`api/environments/${projectId}/logs/attributes`, {
                        attribute_type: 'log',
                        search_values: 'true',
                        ...endpointFilters,
                    }).url,
                    valuesEndpoint: (key) =>
                        combineUrl(`api/environments/${projectId}/logs/values`, {
                            attribute_type: 'log',
                            key: key,
                            ...endpointFilters,
                        }).url,
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopoverHeader: () => 'Log attributes',
                },
                {
                    name: 'Resource attributes',
                    searchPlaceholder: 'resources',
                    type: TaxonomicFilterGroupType.LogResourceAttributes,
                    endpoint: combineUrl(`api/environments/${projectId}/logs/attributes`, {
                        attribute_type: 'resource',
                        search_values: 'true',
                        ...endpointFilters,
                    }).url,
                    valuesEndpoint: (key) =>
                        combineUrl(`api/environments/${projectId}/logs/values`, {
                            attribute_type: 'resource',
                            key: key,
                            ...endpointFilters,
                        }).url,
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopoverHeader: () => 'Resource attributes',
                },
                {
                    name: 'Spans',
                    searchPlaceholder: 'spans',
                    type: TaxonomicFilterGroupType.Spans,
                    options: [
                        { key: 'name', name: 'name', propertyFilterType: 'span' },
                        { key: 'kind', name: 'kind', propertyFilterType: 'span' },
                        { key: 'duration', name: 'duration (ms)', propertyFilterType: 'span' },
                        { key: 'trace_id', name: 'trace_id', propertyFilterType: 'span' },
                        { key: 'span_id', name: 'span_id', propertyFilterType: 'span' },
                        { key: 'status_code', name: 'status code', propertyFilterType: 'span' },
                    ],
                    valuesEndpoint: (key) =>
                        key === 'name'
                            ? combineUrl(`api/environments/${projectId}/tracing/spans/values`, {
                                  attribute_type: 'span',
                                  key: key,
                                  ...endpointFilters,
                              }).url
                            : undefined,
                    localItemsSearch: (items: any[], q: string): any[] => {
                        if (!q) {
                            return items
                        }
                        return [
                            {
                                key: 'message',
                                name: 'Search span message for "' + q + '"',
                                value: q,
                                propertyFilterType: 'span',
                            },
                        ].concat(items.filter((item) => item.name?.toLowerCase().includes(q.toLowerCase())))
                    },
                    getName: (option: { key: string; name: string }) => option.name,
                    getValue: (option: { key: string; name: string }) => option.key,
                    getPopoverHeader: () => 'Span attributes',
                },
                {
                    name: 'Span attributes',
                    searchPlaceholder: 'span attributes',
                    type: TaxonomicFilterGroupType.SpanAttributes,
                    endpoint: combineUrl(`api/environments/${projectId}/tracing/spans/attributes`, {
                        attribute_type: 'span_attribute',
                        ...endpointFilters,
                    }).url,
                    valuesEndpoint: (key) =>
                        combineUrl(`api/environments/${projectId}/tracing/spans/values`, {
                            attribute_type: 'span_attribute',
                            key: key,
                            ...endpointFilters,
                        }).url,
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopoverHeader: () => 'Span attributes',
                },
                {
                    name: 'Span resource attributes',
                    searchPlaceholder: 'span resources',
                    type: TaxonomicFilterGroupType.SpanResourceAttributes,
                    endpoint: combineUrl(`api/environments/${projectId}/tracing/spans/attributes`, {
                        attribute_type: 'span_resource_attribute',
                        ...endpointFilters,
                    }).url,
                    valuesEndpoint: (key) =>
                        combineUrl(`api/environments/${projectId}/tracing/spans/values`, {
                            attribute_type: 'span_resource_attribute',
                            key: key,
                            ...endpointFilters,
                        }).url,
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopoverHeader: () => 'Span resource attributes',
                },
            ],
        ],
    }),
])
