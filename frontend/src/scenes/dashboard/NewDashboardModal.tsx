import { useActions, useValues } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { LemonButton } from '@posthog/lemon-ui'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'
import { DashboardTemplateType } from '~/types'
import { useEffect, useState } from 'react'

import { Field } from 'lib/forms/Field'
import { AvailableFeature } from '~/types'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { DASHBOARD_RESTRICTION_OPTIONS } from './DashboardCollaborators'
import { Form } from 'kea-forms'
import { userLogic } from 'scenes/userLogic'

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

export function OriginalNewDashboardModal(): JSX.Element {
    const { hideNewDashboardModal, createAndGoToDashboard } = useActions(newDashboardLogic)
    const { isNewDashboardSubmitting, newDashboardModalVisible } = useValues(newDashboardLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { templatesList } = useValues(dashboardTemplatesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const dashboardTemplates = !!featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES]

    const templates = dashboardTemplates
        ? templatesList
        : [
              {
                  value: 'DEFAULT_APP',
                  label: 'Product analytics',
                  'data-attr': 'dashboard-select-default-app',
              },
          ]

    return (
        <LemonModal
            title="New dashboard"
            description="Use dashboards to compose multiple insights into a single view."
            onClose={hideNewDashboardModal}
            isOpen={newDashboardModalVisible}
            footer={
                <>
                    <LemonButton
                        form="new-dashboard-form"
                        type="secondary"
                        data-attr="dashboard-cancel"
                        disabled={isNewDashboardSubmitting}
                        onClick={hideNewDashboardModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="new-dashboard-form"
                        type="secondary"
                        data-attr="dashboard-submit-and-go"
                        disabled={isNewDashboardSubmitting}
                        onClick={createAndGoToDashboard}
                    >
                        Create and go to dashboard
                    </LemonButton>
                    <LemonButton
                        form="new-dashboard-form"
                        htmlType="submit"
                        type="primary"
                        data-attr="dashboard-submit"
                        loading={isNewDashboardSubmitting}
                        disabled={isNewDashboardSubmitting}
                    >
                        Create
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={newDashboardLogic}
                formKey="newDashboard"
                id="new-dashboard-form"
                enableFormOnSubmit
                className="space-y-2"
            >
                <Field name="name" label="Name">
                    <LemonInput autoFocus={true} data-attr="dashboard-name-input" className="ph-ignore-input" />
                </Field>
                {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) ? (
                    <Field name="description" label="Description" showOptional>
                        <LemonTextArea data-attr="dashboard-description-input" className="ph-ignore-input" />
                    </Field>
                ) : null}
                <Field name="useTemplate" label="Template" showOptional>
                    <LemonSelect
                        placeholder="Optionally start from template"
                        allowClear
                        options={templates}
                        fullWidth
                        data-attr="copy-from-template"
                    />
                </Field>
                <Field name="restrictionLevel" label="Collaboration settings">
                    {({ value, onChange }) => (
                        <PayGateMini feature={AvailableFeature.DASHBOARD_PERMISSIONING}>
                            <LemonSelect
                                value={value}
                                onChange={onChange}
                                options={DASHBOARD_RESTRICTION_OPTIONS}
                                fullWidth
                            />
                        </PayGateMini>
                    )}
                </Field>
            </Form>
        </LemonModal>
    )
}

export function UpdatedNewDashboardModal(): JSX.Element {
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

export function NewDashboardModal(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            {!!featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES] ? (
                <UpdatedNewDashboardModal />
            ) : (
                <OriginalNewDashboardModal />
            )}
        </>
    )
}
