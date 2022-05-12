import React from 'react'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { More } from 'lib/components/LemonButton/More'
import { Alert, Form, Button, Input, Modal } from 'antd'
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

export const scene: SceneExport = {
    component: Licenses,
    logic: licenseLogic,
}

export function Licenses(): JSX.Element {
    const [form] = Form.useForm()
    const { licenses, licensesLoading, error } = useValues(licenseLogic)
    const { createLicense, deleteLicense } = useActions(licenseLogic)

    const { currentOrganization } = useValues(organizationLogic)

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
                let projectsToDelete = ((currentOrganization?.teams || []) as TeamType[])
                    .filter((team) => !team.is_demo)
                    .sort((a, b) => a.id - b.id)
                projectsToDelete = projectsToDelete.slice(1, projectsToDelete.length)

                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    type="stealth"
                                    style={{ color: 'var(--danger)' }}
                                    onClick={() => {
                                        Modal.confirm({
                                            centered: true,
                                            title: `Cancel license?`,
                                            content: (
                                                <>
                                                    Are you sure you want to cancel your license?
                                                    <ul>
                                                        <li>
                                                            You will <strong>IMMEDIATELY</strong> lose access to all
                                                            premium features such as <strong>multiple projects</strong>,{' '}
                                                            <strong>single sign on</strong>,{' '}
                                                            <strong>group analytics</strong>,{' '}
                                                            <strong>multivariate feature flags</strong> and many more.
                                                        </li>
                                                        {projectsToDelete.length > 0 && (
                                                            <li>
                                                                We will{' '}
                                                                <strong style={{ color: 'var(--danger)' }}>
                                                                    DELETE
                                                                </strong>{' '}
                                                                the following projects:
                                                                <ul>
                                                                    {projectsToDelete.map((team: TeamType) => (
                                                                        <li key={team.id}>
                                                                            <strong>{team.name}</strong>
                                                                        </li>
                                                                    ))}
                                                                </ul>
                                                            </li>
                                                        )}
                                                        <li>
                                                            You will immediately be billed for usage in the current
                                                            period, if any.
                                                        </li>
                                                    </ul>
                                                </>
                                            ),
                                            icon: <ExclamationCircleOutlined />,
                                            okType: 'danger',
                                            okText:
                                                projectsToDelete.length > 0 ? (
                                                    <>Cancel license & delete {projectsToDelete.length} project(s)</>
                                                ) : (
                                                    'Cancel license'
                                                ),
                                            onOk: async function () {
                                                await deleteLicense(license)

                                                return null
                                            },
                                        })
                                    }}
                                    fullWidth
                                >
                                    Cancel license
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div>
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
            {error && (
                <Alert
                    message={
                        error.detail || <span>Could not validate license key. Please try again or contact us.</span>
                    }
                    type="error"
                    style={{ marginBottom: '1em' }}
                />
            )}
            <Form
                form={form}
                name="horizontal_login"
                layout="inline"
                onFinish={(values) => createLicense({ key: values.key })}
                style={{ marginBottom: '1rem' }}
            >
                <Form.Item name="key" rules={[{ required: true, message: 'Please input a license key!' }]}>
                    <Input placeholder="License key" style={{ minWidth: 400 }} />
                </Form.Item>
                <Form.Item shouldUpdate={true}>
                    {() => (
                        <Button
                            type="primary"
                            htmlType="submit"
                            disabled={
                                !form.isFieldsTouched(true) ||
                                !!form.getFieldsError().filter(({ errors }) => errors.length).length
                            }
                        >
                            Activate License Key
                        </Button>
                    )}
                </Form.Item>
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
