import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { cn } from 'lib/utils/css-classes'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateType, TemplateAvailabilityContext } from '~/types'

import BlankDashboardHog from 'public/blank-dashboard-hog.png'

import { runBlankDashboardFlow, runDashboardTemplateClickFlow } from './dashboardTemplateCreationFlows'
import { TemplateItem } from './DashboardTemplateItem'
import { DashboardTemplateItemSkeleton } from './DashboardTemplateItemSkeleton'
import { DashboardTemplateProps, dashboardTemplatesLogic } from './dashboardTemplatesLogic'

export function DashboardTemplateChooser({
    scope = 'default',
    onItemClick,
    redirectAfterCreation = true,
    availabilityContexts,
    className,
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
        runDashboardTemplateClickFlow(template, {
            isLoading,
            newDashboardModalVisible,
            redirectAfterCreation,
            setIsLoading,
            createDashboardFromTemplate,
            showVariableSelectModal,
            setActiveDashboardTemplate,
            onItemClick,
        })
    }

    return (
        <div
            className={cn(
                'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4',
                className
            )}
        >
            {!availabilityContexts || availabilityContexts.includes(TemplateAvailabilityContext.GENERAL) ? (
                <TemplateItem
                    template={{
                        template_name: 'Blank dashboard',
                        dashboard_description: 'Create a blank dashboard',
                        image_url: BlankDashboardHog,
                    }}
                    onClick={() => runBlankDashboardFlow({ isLoading, setIsLoading, addDashboard })}
                    index={0}
                    data-attr="create-dashboard-blank"
                />
            ) : null}
            {allTemplatesLoading ? (
                <>
                    {Array.from({ length: 3 }).map((_, i) => (
                        <DashboardTemplateItemSkeleton key={i} />
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
    )
}
