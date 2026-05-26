import { kea, key, path, props, selectors } from 'kea'

import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'

import { AnyDataNode, NodeKind } from '~/queries/schema/schema-general'

import type { hogQLExpressionTaxonomicGroupsLogicType } from './hogQLExpressionTaxonomicGroupsLogicType'
import { InlineHogQLEditor } from './InlineHogQLEditor'

export const hogQLExpressionTaxonomicGroupsLogic = kea<hogQLExpressionTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'hogQLExpressionTaxonomicGroupsLogic', key]),

    selectors({
        metadataSource: [
            () => [(_, props) => props.metadataSource],
            (metadataSource): AnyDataNode =>
                metadataSource ?? { kind: NodeKind.HogQLQuery, query: 'select event from events' },
        ],
        hogQLExpressionComponentProps: [
            () => [(_, props) => props.hogQLGlobals, (_, props) => props.hogQLExpressionShowBreakdownLabelHint],
            (
                hogQLGlobals: Record<string, any> | undefined,
                showBreakdownLabelHint: boolean | undefined
            ): { globals?: Record<string, any>; showBreakdownLabelHint: boolean } => ({
                globals: hogQLGlobals,
                showBreakdownLabelHint: showBreakdownLabelHint ?? false,
            }),
        ],
        hogQLExpressionTaxonomicGroups: [
            (s) => [s.metadataSource, s.hogQLExpressionComponentProps],
            (metadataSource, hogQLExpressionComponentProps): TaxonomicFilterGroup[] => [
                {
                    name: 'SQL expression',
                    searchPlaceholder: null,
                    categoryLabel: () => 'SQL expression',
                    type: TaxonomicFilterGroupType.HogQLExpression,
                    render: InlineHogQLEditor,
                    getPopoverHeader: () => 'SQL expression',
                    componentProps: { metadataSource, ...hogQLExpressionComponentProps },
                },
            ],
        ],
    }),
])
