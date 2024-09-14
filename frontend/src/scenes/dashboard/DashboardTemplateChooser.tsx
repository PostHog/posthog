import './DashboardTemplateChooser.scss'

import { LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { Spinner } from 'lib/lemon-ui/Spinner'
import BlankDashboardHog from 'public/blank-dashboard-hog.png'
import { useState } from 'react'
import {
    DashboardTemplateProps,
    dashboardTemplatesLogic,
} from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateType } from '~/types'

export function DashboardTemplateChooser({
    scope = 'default',
    onItemClick,
    redirectAfterCreation = true,
}: DashboardTemplateProps): JSX.Element {
    const templatesLogic = dashboardTemplatesLogic({ scope })
    const { allTemplates, allTemplatesLoading } = useValues(templatesLogic)

    const { isLoading, newDashboardModalVisible } = useValues(newDashboardLogic)
    const {
        setActiveDashboardTemplate,
        createDashboardFromTemplate,
        addDashboard,
        setIsLoading,
        showVariableSelectModal,
    } = useActions(newDashboardLogic)

    return (
        <div>
            <div className="DashboardTemplateChooser">
                <TemplateItem
                    template={{
                        template_name: 'Blank dashboard',
                        dashboard_description: 'Create a blank dashboard',
                        image_url: BlankDashboardHog,
                    }}
                    onClick={() => {
                        if (isLoading) {
                            return
                        }
                        setIsLoading(true)
                        addDashboard({
                            name: 'New Dashboard',
                            show: true,
                        })
                    }}
                    index={0}
                    data-attr="create-dashboard-blank"
                />
                {allTemplatesLoading ? (
                    <Spinner className="text-6xl" />
                ) : (
                    allTemplates.map((template, index) => (
                        <TemplateItem
                            key={index}
                            template={template}
                            onClick={() => {
                                if (isLoading) {
                                    return
                                }
                                setIsLoading(true)
                                // while we might receive templates from the external repository
                                // we need to handle templates that don't have variables
                                if ((template.variables || []).length === 0) {
                                    if (template.variables === null) {
                                        template.variables = []
                                    }
                                    createDashboardFromTemplate(
                                        template,
                                        template.variables || [],
                                        redirectAfterCreation
                                    )
                                } else {
                                    if (!newDashboardModalVisible) {
                                        showVariableSelectModal(template)
                                    } else {
                                        setActiveDashboardTemplate(template)
                                    }
                                }
                                onItemClick?.(template)
                            }}
                            index={index + 1}
                            data-attr="create-dashboard-from-template"
                        />
                    ))
                )}
            </div>
        </div>
    )
}

function TemplateItem({
    template,
    onClick,
    index,
    'data-attr': dataAttr,
}: {
    template: Pick<DashboardTemplateType, 'template_name' | 'dashboard_description' | 'image_url' | 'tags'>
    onClick: () => void
    index: number
    'data-attr': string
}): JSX.Element {
    const [isHovering, setIsHovering] = useState(false)

    return (
        <div
            className="cursor-pointer border rounded TemplateItem flex flex-col transition-all"
            onClick={onClick}
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => setIsHovering(false)}
            data-attr={dataAttr}
        >
            <div
                className={clsx('transition-all w-full overflow-hidden', isHovering ? 'h-4 min-h-4' : 'h-30 min-h-30')}
            >
                <FallbackCoverImage src={template?.image_url} alt="cover photo" index={index} imageClassName="h-30" />
            </div>

            <h5 className="px-2 mb-1">{template?.template_name}</h5>
            <div className="flex gap-x-1 px-2 mb-1">
                {template.tags?.map((tag, index) => (
                    <LemonTag key={index} type="option">
                        {tag}
                    </LemonTag>
                ))}
            </div>
            <div className="px-2 py-1 overflow-y-auto grow">
                <p className={clsx('text-muted-alt text-xs', isHovering ? '' : 'line-clamp-2')}>
                    {template?.dashboard_description ?? ' '}
                </p>
            </div>
        </div>
    )
}
