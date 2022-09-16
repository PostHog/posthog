import React from 'react'
import { More } from 'lib/components/LemonButton/More'
import { isLicenseExpired, licenseLogic } from './licenseLogic'
import { useValues, useActions } from 'kea'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { CodeSnippet } from 'scenes/ingestion/frameworks/CodeSnippet'
import { PageHeader } from 'lib/components/PageHeader'
import { InfoCircleOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LicenseType, TeamType } from '~/types'
import { LemonButton } from 'lib/components/LemonButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { dayjs } from 'lib/dayjs'
import { LemonModal } from 'lib/components/LemonModal'
import { Form } from 'kea-forms'
import { LemonInput } from '@posthog/lemon-ui'
import { Field } from 'lib/forms/Field'

export const scene: SceneExport = {
    component: Licenses,
    logic: licenseLogic,
}

function ConfirmCancelModal({
    licenses,
    isOpen,
    onCancel,
    onOk,
}: {
    licenses: LicenseType[]
    isOpen: boolean
    onCancel: () => void
    onOk: () => void
}): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const hasAnotherValidLicense = licenses.filter((license) => dayjs().isBefore(license.valid_until)).length > 1

    const nonDemoProjects = ((currentOrganization?.teams || []) as TeamType[])
        .filter((team) => !team.is_demo)
        .sort((a, b) => a.id - b.id)
    const willDeleteProjects = !hasAnotherValidLicense && nonDemoProjects.slice(1, nonDemoProjects.length).length > 0

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onCancel}
            title="Are you sure you want to deactivate your license?"
            footer={
                <>
                    <LemonButton
                        form="new-dashboard-form"
                        type="secondary"
                        data-attr="deactivate-license-cancel"
                        className="mr-2"
                        onClick={onCancel}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton data-attr="deactivate-license-proceed" type="primary" status="danger" onClick={onOk}>
                        {willDeleteProjects ? (
                            <>Deactivate license & delete {nonDemoProjects.length} project(s)</>
                        ) : (
                            'Deactivate license'
                        )}
                    </LemonButton>
                </>
            }
        >
            <ul className="pl-3 list-disc">
                {!hasAnotherValidLicense ? (
                    <li>
                        You will <strong>IMMEDIATELY</strong> lose access to all premium features such as{' '}
                        <strong>multiple projects</strong>, <strong>single sign on</strong>,{' '}
                        <strong>group analytics</strong>, <strong>multivariate feature flags</strong> and many more.
                    </li>
                ) : (
                    <li>
                        You will <strong>keep</strong> all premium features available with your other valid license.
                    </li>
                )}
                {willDeleteProjects && (
                    <li>
                        We will <strong className="text-danger">DELETE</strong> the following projects:
                        <ul className="pl-6 list-disc mb-2">
                            {nonDemoProjects.map((team: TeamType) => (
                                <li key={team.id}>
                                    <strong>{team.name}</strong>
                                </li>
                            ))}
                        </ul>
                        To keep one of these projects instead, remove all other projects first.
                    </li>
                )}
                <li>You will immediately be billed for usage in the current period, if any.</li>
            </ul>
        </LemonModal>
    )
}

export function Licenses(): JSX.Element {
    const {
        licenses,
        licensesLoading,
        activateLicense,
        activateLicenseAllErrors,
        isActivateLicenseSubmitting,
        showConfirmCancel,
    } = useValues(licenseLogic)
    const { deleteLicense, setShowConfirmCancel } = useActions(licenseLogic)

    const columns: LemonTableColumns<LicenseType> = [
        {
            title: 'Active',
            render: function renderActive(_, license: LicenseType) {
                return isLicenseExpired(license) ? 'expired' : 'active'
            },
        },
        {
            title: 'Valid until',
            render: function renderActive(_, license: LicenseType) {
                return humanFriendlyDetailedTime(license.valid_until)
            },
        },
        {
            title: 'Plan',
            dataIndex: 'plan',
        },
        {
            title: function Render() {
                return (
                    <Tooltip
                        placement="right"
                        title="Maximum number of team members that you can have across all organizations with your current license."
                    >
                        Max # of team members
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                )
            },
            render: function renderMaxUsers(_, license: LicenseType) {
                return license.max_users === null ? 'Unlimited' : license.max_users
            },
        },
        {
            title: 'Key',
            render: function renderActive(_, license: LicenseType) {
                return <CodeSnippet>{license.key}</CodeSnippet>
            },
        },
        {
            title: 'License added on',
            render: function renderActive(_, license: LicenseType) {
                return humanFriendlyDetailedTime(license.created_at)
            },
        },
        {
            width: 0,
            render: function renderActive(_, license: LicenseType) {
                if (dayjs().isAfter(license.valid_until)) {
                    return null
                }
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton status="danger" onClick={() => setShowConfirmCancel(license)} fullWidth>
                                    Deactivate license
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    console.log(activateLicense, activateLicenseAllErrors)

    return (
        <div>
            <ConfirmCancelModal
                licenses={licenses}
                isOpen={!!showConfirmCancel}
                onCancel={() => setShowConfirmCancel(null)}
                onOk={() => (showConfirmCancel ? deleteLicense(showConfirmCancel) : null)}
            />
            <PageHeader
                title="Licenses"
                caption={
                    <>
                        Here you can add and manage your PostHog enterprise licenses. When you activate a license key,
                        enterprise functionality will be enabled immediately. Contact{' '}
                        <a href="mailto:sales@posthog.com">sales@posthog.com</a> to buy a license or if you have any
                        issues with a license.
                    </>
                }
            />

            <Form
                logic={licenseLogic}
                formKey="activateLicense"
                className="flex flex-row gap-2 my-4 items-start"
                enableFormOnSubmit
            >
                <Field name="key">
                    <LemonInput placeholder="License key" fullWidth />
                </Field>

                <LemonButton type="primary" htmlType="submit" loading={isActivateLicenseSubmitting}>
                    Activate license key
                </LemonButton>
            </Form>
            <LemonTable
                data-attr="license-table"
                size="small"
                rowKey="id"
                rowClassName="cursor-pointer"
                dataSource={licenses}
                columns={columns}
                loading={licensesLoading}
            />
        </div>
    )
}
