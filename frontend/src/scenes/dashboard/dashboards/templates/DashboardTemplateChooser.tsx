import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateType, TemplateAvailabilityContext } from '~/types'

import BlankDashboardHog from 'public/blank-dashboard-hog.png'

import { TemplateItem } from './DashboardTemplateItem'
import { DashboardTemplateProps, dashboardTemplatesLogic } from './dashboardTemplatesLogic'

export function DashboardTemplateChooser({
    scope = 'default',
    onItemClick,
    redirectAfterCreation = true,
    availabilityContexts,
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

    const filteredTemplates = useMemo(() => {
        return allTemplates.filter((template) => {
            if (availabilityContexts) {
                return availabilityContexts.some((context) => template.availability_contexts?.includes(context))
            }
            return true
        })
    }, [allTemplates, availabilityContexts])

    const handleTemplateClick = (template: DashboardTemplateType): void => {
        if (isLoading) {
            return
        }
        setIsLoading(true)
        const variables = template.variables ?? []
        if (variables.length === 0) {
            createDashboardFromTemplate(template, variables, redirectAfterCreation)
        } else {
            if (!newDashboardModalVisible) {
                showVariableSelectModal(template)
            } else {
                setActiveDashboardTemplate(template)
            }
        }
        onItemClick?.(template)
    }

    return (
        <div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 max-w-[1000px]">
                {!availabilityContexts || availabilityContexts.includes(TemplateAvailabilityContext.GENERAL) ? (
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
                                _create_in_folder: 'Unfiled/Dashboards',
                            })
                        }}
                        index={0}
                        data-attr="create-dashboard-blank"
                    />
                ) : null}
                {allTemplatesLoading ? (
                    <>
                        {Array.from({ length: 2 }).map((_, i) => (
                            <TemplateItemSkeleton key={i} />
                        ))}
                    </>
                ) : (
                    filteredTemplates.map((template, index) => (
                        <TemplateItem
                            key={template.id}
                            template={template}
                            onClick={() => handleTemplateClick(template)}
                            index={index + 1}
                            data-attr="create-dashboard-from-template"
                        />
                    ))
                )}
            </div>
        </div>
    )
}

/** Placeholder grid cells that mirror `TemplateItem` layout (cover, title, description). */
function TemplateItemSkeleton(): JSX.Element {
    return (
        <div
            className="border rounded TemplateItem flex flex-col pointer-events-none select-none w-full h-[210px]"
            aria-hidden
        >
            <div className="h-30 min-h-30 w-full overflow-hidden">
                <LemonSkeleton className="h-30 w-full rounded-none" />
            </div>
            <div className="px-2 py-1">
                <div className="mb-1">
                    <LemonSkeleton className="h-5 w-4/5" />
                </div>
                <div className="py-1 grow flex flex-col gap-1">
                    <LemonSkeleton className="h-3 w-full" />
                    <LemonSkeleton className="h-3 w-[92%]" />
                </div>
            </div>
        </div>
    )
}
