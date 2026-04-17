import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { PropertyOperator } from '~/types'

const URL_PROPERTY_KEYS = ['$current_url', '$pathname']

const URL_OPERATOR_ALLOWLIST: PropertyOperator[] = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.IContains,
    PropertyOperator.NotIContains,
    PropertyOperator.Regex,
    PropertyOperator.NotRegex,
    PropertyOperator.IsSet,
    PropertyOperator.IsNotSet,
    PropertyOperator.IsCleanedPathExact,
]

export function HeatmapUrlFilter(): JSX.Element {
    const { urlProperties, doPathCleaning } = useValues(heatmapDataLogic({ context: 'in-app' }))
    const { setUrlProperties, setDoPathCleaning } = useActions(heatmapDataLogic({ context: 'in-app' }))

    return (
        <div className="flex flex-col gap-2">
            <PropertyFilters
                pageKey="heatmap-url-filter"
                propertyFilters={urlProperties}
                onChange={setUrlProperties}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                propertyAllowList={{ [TaxonomicFilterGroupType.EventProperties]: URL_PROPERTY_KEYS }}
                operatorAllowlist={URL_OPERATOR_ALLOWLIST}
                buttonText="Add URL filter"
                addText="Add URL filter"
            />
            {urlProperties.length > 0 ? (
                <div className="flex items-center gap-2">
                    <LemonSwitch
                        checked={doPathCleaning}
                        onChange={setDoPathCleaning}
                        label="Apply path cleaning rules"
                        bordered={false}
                    />
                    <Link to={urls.settings('project-product-analytics', 'path-cleaning')} target="_blank">
                        Manage rules
                    </Link>
                </div>
            ) : null}
        </div>
    )
}
