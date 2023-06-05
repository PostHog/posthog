import { useActions, useValues } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { LemonButton } from '@posthog/lemon-ui'
import { dashboardTemplateVariablesLogic } from './dashboardTemplateVariablesLogic'
import { DashboardTemplateScope, DashboardTemplateType, FeatureFlagType } from '~/types'
import { useState } from 'react'

import { pluralize } from 'lib/utils'

import BlankDashboardHog from 'public/blank-dashboard-hog.png'
import './NewDashboardModal.scss'
import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import clsx from 'clsx'

function TemplateItem({
    template,
    onClick,
    index,
    'data-attr': dataAttr,
}: {
    template: Pick<DashboardTemplateType, 'template_name' | 'dashboard_description' | 'image_url'>
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
            <div className="px-2 py-1 overflow-y-auto grow">
                <p className={clsx('text-muted-alt text-xs', isHovering ? '' : 'line-clamp-2')}>
                    {template?.dashboard_description ?? ' '}
                </p>
            </div>
        </div>
    )
}

export function DashboardTemplatePreview({ featureFlagId }: { featureFlagId?: number }): JSX.Element {
    const _newDashboardLogic = newDashboardLogic({ featureFlagId })
    const { activeDashboardTemplate } = useValues(_newDashboardLogic)
    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const { createDashboardFromTemplate, clearActiveDashboardTemplate } = useActions(_newDashboardLogic)

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

interface DashboardTemplateChooserProps {
    scope?: DashboardTemplateScope
    featureFlagId?: number
}

export function DashboardTemplateChooser({
    scope = 'global',
    featureFlagId,
}: DashboardTemplateChooserProps): JSX.Element {
    const templatesLogic = dashboardTemplatesLogic({ scope })
    const { allTemplates } = useValues(templatesLogic)

    const _newDashboardLogic = newDashboardLogic({ featureFlagId })
    const { isLoading } = useValues(_newDashboardLogic)
    const { setActiveDashboardTemplate, createDashboardFromTemplate, addDashboard, setIsLoading } =
        useActions(_newDashboardLogic)

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
                {allTemplates.map((template, index) => (
                    <TemplateItem
                        key={index}
                        template={template}
                        onClick={() => {
                            if (isLoading) {
                                return
                            }
                            setIsLoading(true)
                            console.log('HERE')
                            // while we might receive templates from the external repository
                            // we need to handle templates that don't have variables
                            if ((template.variables || []).length === 0) {
                                if (template.variables === null) {
                                    template.variables = []
                                }
                                createDashboardFromTemplate(template, template.variables || [])
                                setActiveDashboardTemplate(template)
                            }
                        }}
                        index={index + 1}
                        data-attr="create-dashboard-from-template"
                    />
                ))}
                {/*TODO @lukeharries should we have an empty state here? When no templates let people know what to do?*/}
            </div>
        </div>
    )
}

export function NewDashboardModal({ featureFlag }: { featureFlag?: FeatureFlagType }): JSX.Element {
    const _newDashboardLogic = featureFlag
        ? newDashboardLogic({ featureFlagId: featureFlag.id as number })
        : newDashboardLogic
    const { hideNewDashboardModal } = useActions(_newDashboardLogic)
    const { newDashboardModalVisible } = useValues(_newDashboardLogic)

    const { activeDashboardTemplate } = useValues(_newDashboardLogic)

    const _dashboardTemplateChooser = featureFlag ? (
        <DashboardTemplateChooser scope="feature_flag" featureFlagId={featureFlag.id as number} />
    ) : (
        <DashboardTemplateChooser />
    )

    const _dashboardTemplatePreview = featureFlag ? (
        <DashboardTemplatePreview featureFlagId={featureFlag.id as number} />
    ) : (
        <DashboardTemplatePreview />
    )

    return (
        <LemonModal
            onClose={hideNewDashboardModal}
            isOpen={newDashboardModalVisible}
            title={activeDashboardTemplate ? 'Setup your events' : 'Create a dashboard'}
            description={
                activeDashboardTemplate
                    ? `The dashboard template you selected requires you to set up ${pluralize(
                          (activeDashboardTemplate.variables || []).length,
                          'event',
                          'events',
                          true
                      )}.`
                    : 'Choose a template or start with a blank slate'
            }
        >
            <div className="NewDashboardModal">
                {activeDashboardTemplate ? _dashboardTemplatePreview : _dashboardTemplateChooser}
            </div>
        </LemonModal>
    )
}
