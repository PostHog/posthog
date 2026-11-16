import { capitalizeFirstLetter } from 'lib/utils/strings'

import { Noun } from '~/models/groupsModel'

import { MathDefinition } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

const PROPERTY_MATHS = ['sum', 'avg', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']

export interface MathTagLabelInput {
    math: string | undefined
    mathHogQL: string | undefined | null
    mathGroupTypeIndex: number | null | undefined
    mathDefinitions: Partial<Record<string, MathDefinition>>
    aggregationLabel: (groupTypeIndex: number | null | undefined) => Noun
}

/** The text of the tag that names how a series is counted, such as "Unique" or "Weekly active users". */
export function mathTagLabel({
    math,
    mathHogQL,
    mathGroupTypeIndex,
    mathDefinitions,
    aggregationLabel,
}: MathTagLabelInput): string {
    if (!math || math === 'total') {
        return 'Total'
    }
    if (math === 'dau') {
        return 'Unique'
    }
    if (math === 'unique_group' && mathGroupTypeIndex != undefined) {
        return `Unique ${aggregationLabel(mathGroupTypeIndex).plural}`
    }
    if (math === 'weekly_active' && mathGroupTypeIndex != undefined) {
        return `Weekly active ${aggregationLabel(mathGroupTypeIndex).plural}`
    }
    if (math === 'monthly_active' && mathGroupTypeIndex != undefined) {
        return `Monthly active ${aggregationLabel(mathGroupTypeIndex).plural}`
    }
    if (math === 'hogql') {
        return String(mathHogQL) || 'SQL'
    }
    return mathDefinitions[math]?.name || capitalizeFirstLetter(math)
}

/** Whether the tag is followed by "of <property>", as in "Sum of revenue". */
export function isPropertyMath(math: string | undefined): boolean {
    return !!math && PROPERTY_MATHS.includes(math)
}
