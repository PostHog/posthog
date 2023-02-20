import { useActions, useValues } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
// import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
// import { FEATURE_FLAGS } from 'lib/constants'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { LemonButton } from '@posthog/lemon-ui'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'
import { DashboardTemplateType } from '~/types'
import { useEffect, useState } from 'react'

function FallbackCoverImage({ src, alt, index }: { src: string | undefined; alt: string; index: number }): JSX.Element {
    const [hasError, setHasError] = useState(false)
    const [color, setColor] = useState('#ff0000')

    const handleImageError = (): void => {
        setHasError(true)
    }

    const colors = ['#ff0000', '#ffa500', '#ffff00', '#008000', '#0000ff', '#4b0082', '#ee82ee', '#800080', '#ffc0cb']

    useEffect(() => {
        setColor(colors[(index * 3) % colors.length])
    }, [index])

    return (
        <>
            {hasError || !src ? (
                <div
                    className="w-full h-full"
                    // dynamic color based on index
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        background: `${color}`,
                    }}
                />
            ) : (
                <img className="w-full h-full object-cover" src={src} alt={alt} onError={handleImageError} />
            )}
        </>
    )
}

function TemplateItem({
    template,
    onClick,
    index,
}: {
    template: Pick<DashboardTemplateType, 'template_name' | 'dashboard_description' | 'image_url'>
    onClick: () => void
    index: number
}): JSX.Element {
    return (
        <div
            className="cursor-pointer border-2 rounded"
            onClick={onClick}
            style={{
                width: '240px',
                height: '210px',
            }}
        >
            <div className="w-full h-120 overflow-hidden">
                <FallbackCoverImage src={template?.image_url} alt="cover photo" index={index} />
            </div>

            <div className="p-2">
                <p className="truncate mb-1">{template?.template_name}</p>
                <p className="text-muted-alt text-xs line-clamp-2">{template?.dashboard_description ?? ' '}</p>
            </div>
        </div>
    )
}

export function DashboardTemplatePreview(): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const { createDashboardFromTemplate, clearActiveDashboardTemplate } = useActions(newDashboardLogic)

    return (
        <div>
            <DashboardTemplateVariables />

            <div className="flex justify-between my-4">
                <LemonButton onClick={clearActiveDashboardTemplate} type="secondary">
                    Back
                </LemonButton>
                <LemonButton
                    onClick={() => {
                        activeDashboardTemplate && createDashboardFromTemplate(activeDashboardTemplate, variables)
                    }}
                    type="primary"
                >
                    Create
                </LemonButton>
            </div>
        </div>
    )
}

export function DashboardTemplateChooser(): JSX.Element {
    const { allTemplates } = useValues(dashboardTemplatesLogic)
    const { addDashboard } = useActions(newDashboardLogic)

    const { setActiveDashboardTemplate } = useActions(newDashboardLogic)

    return (
        <div>
            <div
                className="flex flex-wrap gap-4"
                style={{
                    maxWidth: '780px',
                }}
            >
                <TemplateItem
                    template={{
                        template_name: 'Blank dashboard',
                        dashboard_description: 'Create a blank dashboard',
                        image_url:
                            'https://posthog.com/static/e49bbe6af9a669f1c07617e5cd2e3229/a764f/marketing-hog.jpg',
                    }}
                    onClick={() =>
                        addDashboard({
                            name: 'New Dashboard',
                            show: true,
                        })
                    }
                    index={0}
                />
                {allTemplates.map((template, index) => (
                    <TemplateItem
                        key={index}
                        template={template}
                        onClick={() => {
                            if (template.variables.length === 0) {
                                addDashboard({
                                    name: template.template_name,
                                    show: true,
                                })
                                return
                            } else {
                                setActiveDashboardTemplate(template)
                            }
                        }}
                        index={index + 1}
                    />
                ))}
            </div>
        </div>
    )
}

export function NewDashboardModal(): JSX.Element {
    const { hideNewDashboardModal } = useActions(newDashboardLogic)
    const { newDashboardModalVisible } = useValues(newDashboardLogic)

    const { activeDashboardTemplate } = useValues(newDashboardLogic)

    return (
        <LemonModal
            onClose={hideNewDashboardModal}
            isOpen={newDashboardModalVisible}
            title={activeDashboardTemplate ? 'Setup your events' : 'Create a dashboard'}
            description={
                activeDashboardTemplate
                    ? `The dashboard template you selected requires you to set up ${
                          activeDashboardTemplate.variables.length
                      } event${activeDashboardTemplate.variables.length > 1 ? 's' : ''}.`
                    : 'Choose a template or start with a blank slate'
            }
        >
            {activeDashboardTemplate ? <DashboardTemplatePreview /> : <DashboardTemplateChooser />}
        </LemonModal>
    )
}
