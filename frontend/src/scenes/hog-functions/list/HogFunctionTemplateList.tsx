import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconMegaphone, IconPencil, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { isManagedSourceTemplate } from 'scenes/data-warehouse/utils'

import { AccessControlLevel, AccessControlResourceType, HogFunctionTemplateType } from '~/types'

import { HogFunctionIcon } from '../configuration/HogFunctionIcon'
import { HogFunctionStatusTag } from '../misc/HogFunctionStatusTag'
import { hogFunctionRequestModalLogic } from './hogFunctionRequestModalLogic'
import { HogFunctionTemplateListLogicProps, hogFunctionTemplateListLogic } from './hogFunctionTemplateListLogic'

export function HogFunctionTemplateList({
    extraControls,
    hideFeedback = false,
    ...props
}: HogFunctionTemplateListLogicProps & { extraControls?: JSX.Element; hideFeedback?: boolean }): JSX.Element {
    const {
        loading,
        filteredTemplates,
        filteredUserTemplates,
        filters,
        templates,
        urlForTemplate,
        editUrlForTemplate,
    } = useValues(hogFunctionTemplateListLogic(props))
    const { loadHogFunctionTemplates, setFilters, resetFilters, registerInterest, deleteUserTemplate } = useActions(
        hogFunctionTemplateListLogic(props)
    )
    const { openFeedbackDialog } = useActions(hogFunctionRequestModalLogic)

    useEffect(() => loadHogFunctionTemplates(), [props.type]) // oxlint-disable-line exhaustive-deps

    const templateColumns = (options?: {
        showUserTemplateActions?: boolean
    }): LemonTable<HogFunctionTemplateType>['props']['columns'] => [
        {
            title: '',
            width: 0,
            render: function RenderIcon(_, template) {
                return <HogFunctionIcon src={template.icon_url} className={template.icon_class_name} size="small" />
            },
        },
        {
            title: 'Name',
            sticky: true,
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
            key: 'name',
            dataIndex: 'name',
            render: (_, template) => {
                const isUserTemplate = !!(template as any).user_template_id
                const hasAccess =
                    !isManagedSourceTemplate(template) ||
                    !getAccessControlDisabledReason(
                        AccessControlResourceType.ExternalDataSource,
                        AccessControlLevel.Editor
                    )
                return (
                    <LemonTableLink
                        to={hasAccess ? (urlForTemplate(template) ?? undefined) : undefined}
                        title={
                            <>
                                {template.name}
                                {isUserTemplate && (
                                    <LemonTag type="highlight" className="ml-1">
                                        {(template as any).user_template_scope === 'organization' ? 'Org' : 'Project'}
                                    </LemonTag>
                                )}
                                {template.status && !isUserTemplate && (
                                    <HogFunctionStatusTag status={template.status} />
                                )}
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
                const dataWarehouseSourceAccessDisabledReason =
                    isManagedSourceTemplate(template) &&
                    getAccessControlDisabledReason(
                        AccessControlResourceType.ExternalDataSource,
                        AccessControlLevel.Editor
                    )

                if (template.status === 'coming_soon') {
                    return (
                        <LemonButton
                            type="primary"
                            data-attr="request-destination"
                            icon={<IconMegaphone />}
                            className="whitespace-nowrap"
                            onClick={() => registerInterest(template)}
                        >
                            Notify me
                        </LemonButton>
                    )
                }

                return (
                    <div className="flex items-center gap-1">
                        <LemonButton
                            type="primary"
                            data-attr="new-destination"
                            icon={<IconPlusSmall />}
                            to={urlForTemplate(template) ?? undefined}
                            disabledReason={dataWarehouseSourceAccessDisabledReason ?? undefined}
                        >
                            Create
                        </LemonButton>
                        {options?.showUserTemplateActions && (
                            <>
                                <LemonButton
                                    size="small"
                                    icon={<IconPencil />}
                                    tooltip="Edit template"
                                    to={editUrlForTemplate(template) ?? undefined}
                                />
                                <LemonButton
                                    status="danger"
                                    size="small"
                                    icon={<IconTrash />}
                                    tooltip="Delete template"
                                    onClick={() => deleteUserTemplate((template as any).user_template_id)}
                                />
                            </>
                        )}
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex gap-2 items-center">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    value={filters.search ?? ''}
                    onChange={(e) => setFilters({ search: e })}
                />
                {!hideFeedback ? (
                    <Link className="text-sm font-semibold" subtle onClick={() => openFeedbackDialog(props.type)}>
                        Can't find what you're looking for?
                    </Link>
                ) : null}
                <div className="flex-1" />
                {extraControls}
            </div>

            {filteredUserTemplates.length > 0 && (
                <div className="flex flex-col gap-2">
                    <h3 className="mb-0">Custom templates</h3>
                    <LemonTable
                        dataSource={filteredUserTemplates}
                        size="small"
                        loading={loading}
                        columns={templateColumns({ showUserTemplateActions: true })}
                    />
                </div>
            )}

            <LemonTable
                dataSource={filteredTemplates}
                size="small"
                loading={loading}
                columns={templateColumns()}
                emptyState={
                    templates.length === 0 && !loading ? (
                        'No results found'
                    ) : (
                        <>
                            Nothing found matching filters. <Link onClick={() => resetFilters()}>Clear filters</Link>
                        </>
                    )
                }
            />
        </div>
    )
}
