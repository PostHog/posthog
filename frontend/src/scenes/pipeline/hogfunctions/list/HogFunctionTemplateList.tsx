import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PayGateButton } from 'lib/components/PayGateMini/PayGateButton'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { AvailableFeature, PipelineStage } from '~/types'

import { HogFunctionIcon } from '../HogFunctionIcon'
import { hogFunctionTemplateListLogic, HogFunctionTemplateListLogicProps } from './hogFunctionTemplateListLogic'

export function HogFunctionTemplateList({
    extraControls,
    ...props
}: HogFunctionTemplateListLogicProps & { extraControls?: JSX.Element }): JSX.Element {
    const { loading, filteredTemplates, filters, templates, canEnableHogFunction, urlForTemplate } = useValues(
        hogFunctionTemplateListLogic(props)
    )
    const { loadHogFunctionTemplates, setFilters, resetFilters } = useActions(hogFunctionTemplateListLogic(props))

    useEffect(() => loadHogFunctionTemplates(), [])

    return (
        <>
            <div className="flex items-center mb-2 gap-2">
                {!props.forceFilters?.search && (
                    <LemonInput
                        type="search"
                        placeholder="Search..."
                        value={filters.search ?? ''}
                        onChange={(e) => setFilters({ search: e })}
                    />
                )}
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
                                    to={urls.pipelineNodeNew(PipelineStage.Destination, `hog-${template.id}`)}
                                    title={template.name}
                                    description={template.description}
                                />
                            )
                        },
                    },

                    {
                        width: 0,
                        render: function Render(_, template) {
                            const url = urlForTemplate(template)

                            return canEnableHogFunction(template) ? (
                                <LemonButton
                                    type="primary"
                                    data-attr={`new-${PipelineStage.Destination}`}
                                    icon={<IconPlusSmall />}
                                    to={url}
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
