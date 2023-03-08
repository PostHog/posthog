import { useEffect } from 'react'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Alert, Form, Button, Input } from 'antd'
import { isLicenseExpired, licenseLogic } from './licenseLogic'
import { useValues, useActions } from 'kea'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LicenseType, TeamType } from '~/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { dayjs } from 'lib/dayjs'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { billingLogic } from 'scenes/billing/billingLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

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
    const { billingVersion } = useValues(billingLogic)
    const hasAnotherValidLicense = licenses.filter((license) => dayjs().isBefore(license.valid_until)).length > 1

    const nonDemoProjects = ((currentOrganization?.teams || []) as TeamType[])
        .filter((team) => !team.is_demo)
        .sort((a, b) => a.id - b.id)
    const willDeleteProjects = !hasAnotherValidLicense && nonDemoProjects.slice(1, nonDemoProjects.length).length > 0

    useEffect(() => {
        // If billing V2 is enabled then we should go to the unified billing page
        if (billingVersion === 'v2') {
            router.actions.push(urls.organizationBilling())
        }
    }, [billingVersion])

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
    const [form] = Form.useForm()
    const { licenses, licensesLoading, error, showConfirmCancel } = useValues(licenseLogic)
    const { createLicense, deleteLicense, setShowConfirmCancel } = useActions(licenseLogic)

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
