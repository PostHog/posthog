import { Link } from '@posthog/lemon-ui'
import { connect, kea, path, selectors } from 'kea'
import { MANUAL_SOURCE_LINK_MAP, sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { DATA_WAREHOUSE_SOURCE_ICON_MAP } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { HogFunctionTemplateType, SourceConfig } from '~/types'

import type { nonHogFunctionTemplatesLogicType } from './nonHogFunctionTemplatesLogicType'

export const nonHogFunctionTemplatesLogic = kea<nonHogFunctionTemplatesLogicType>([
    path((key) => ['scenes', 'data-pipelines', 'utils', 'nonHogFunctionTemplatesLogic', key]),

    connect(() => ({
        values: [sourceWizardLogic, ['connectors']],
    })),

    selectors({
        hogFunctionTemplatesDataWarehouseSources: [
            (s) => [s.connectors],
            (connectors): HogFunctionTemplateType[] => {
                const managed = connectors.map(
                    (connector: SourceConfig): HogFunctionTemplateType => ({
                        id: `managed-${connector.name}`,
                        type: 'source_webhook',
                        name: connector.name,
                        icon_url: DATA_WAREHOUSE_SOURCE_ICON_MAP[connector.name],
                        status: connector.unreleasedSource ? 'coming_soon' : 'stable',
                        description: (
                            <>
                                Data will be synced to PostHog and regularly refreshed.{' '}
                                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
                            </>
                        ),
                        hog: '',
                        inputs_schema: [],
                        filters: null,
                        masking: null,
                        free: true,
                    })
                )

                const selfManaged = Object.entries(MANUAL_SOURCE_LINK_MAP).map(
                    ([type, name]): HogFunctionTemplateType => ({
                        id: `self-managed-${type}`,
                        type: 'source_webhook',
                        name,
                        icon_url: DATA_WAREHOUSE_SOURCE_ICON_MAP[type],
                        status: 'stable',
                        description: (
                            <>
                                Data will be queried directly from your data source that you manage.{' '}
                                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
                            </>
                        ),
                        hog: '',
                        inputs_schema: [],
                        filters: null,
                        masking: null,
                        free: true,
                    })
                )

                return [...managed, ...selfManaged]
            },
        ],
    }),
])
