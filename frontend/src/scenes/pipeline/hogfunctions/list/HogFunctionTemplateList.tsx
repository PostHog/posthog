import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PayGateButton } from 'lib/components/PayGateMini/PayGateButton'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect } from 'react'
import { DestinationTag } from 'scenes/pipeline/destinations/DestinationTag'

import { AvailableFeature, PipelineStage } from '~/types'

import { HogFunctionIcon } from '../HogFunctionIcon'
import { hogFunctionTemplateListLogic, HogFunctionTemplateListLogicProps } from './hogFunctionTemplateListLogic'

export function HogFunctionTemplateList({
    extraControls,
    showSearch = true,
    ...props
}: HogFunctionTemplateListLogicProps & { extraControls?: JSX.Element; showSearch?: boolean }): JSX.Element {
    const { loading, filteredTemplates, filters, templates, canEnableHogFunction, urlForTemplate } = useValues(
        hogFunctionTemplateListLogic(props)
    )
    const { loadHogFunctionTemplates, setFilters, resetFilters } = useActions(hogFunctionTemplateListLogic(props))

    useEffect(() => loadHogFunctionTemplates(), [props.type, props.subTemplateId])

    return (
        <>
            <div className="flex items-center gap-2 mb-2">
                {!props.forceFilters?.search && showSearch ? (
                    <LemonInput
                        type="search"
                        placeholder="Search..."
                        value={filters.search ?? ''}
                        onChange={(e) => setFilters({ search: e })}
                    />
                ) : null}
                <div className="flex-1" />
                {extraControls}
            </div>

            <LemonTable
                dataSource={filteredTemplates}
                size="small"
                loading={loading}
                columns={[
                    {
                        title: '',
                        width: 0,
                        render: function RenderIcon(_, template) {
                            return <HogFunctionIcon src={template.icon_url} size="small" />
                        },
                    },
                    {
                        title: 'Name',
                        sticky: true,
                        sorter: true,
                        key: 'name',
                        dataIndex: 'name',
                        render: (_, template) => {
                            return (
                                <LemonTableLink
                                    to={urlForTemplate(template)}
                                    title={
                                        <>
                                            {template.name}
                                            {template.status && <DestinationTag status={template.status} />}
                                        </>
                                    }
                                    description={template.description}
                                />
                            )
                        },
                    },

                    {
                        width: 0,
                        render: function Render(_, template) {
                            return canEnableHogFunction(template) ? (
                                <LemonButton
                                    type="primary"
                                    data-attr={`new-${PipelineStage.Destination}`}
                                    icon={<IconPlusSmall />}
                                    to={urlForTemplate(template)}
                                    fullWidth
                                >
                                    Create
                                </LemonButton>
                            ) : (
                                <span className="whitespace-nowrap">
                                    <PayGateButton feature={AvailableFeature.DATA_PIPELINES} type="secondary" />
                                </span>
                            )
                        },
                    },
                ]}
                emptyState={
                    templates.length === 0 && !loading ? (
                        'No results found'
                    ) : (
                        <>
                            Nothing found matching filters. <Link onClick={() => resetFilters()}>Clear filters</Link>{' '}
                        </>
                    )
                }
            />
        </>
    )
}
