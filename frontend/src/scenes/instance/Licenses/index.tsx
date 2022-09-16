import React, { useState } from 'react'
import { More } from 'lib/components/LemonButton/More'
import { isLicenseExpired, licenseLogic } from './licenseLogic'
import { useValues, useActions } from 'kea'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { CodeSnippet } from 'scenes/ingestion/frameworks/CodeSnippet'
import { PageHeader } from 'lib/components/PageHeader'
import { Tooltip } from 'lib/components/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LicenseType, TeamType } from '~/types'
import { LemonButton } from 'lib/components/LemonButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { dayjs } from 'lib/dayjs'
import { LemonModal } from 'lib/components/LemonModal'
import { Form } from 'kea-forms'
import { LemonCheckbox, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'
import { Field } from 'lib/forms/Field'
import { IconInfo } from 'lib/components/icons'

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
    const { licenses, licensesLoading, isActivateLicenseSubmitting, showConfirmCancel } = useValues(licenseLogic)
    const { deleteLicense, setShowConfirmCancel } = useActions(licenseLogic)

    const [showExistingForm, setShowExistingForm] = useState(false)

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
            title: (
                <Tooltip
                    placement="right"
                    title="Maximum number of team members that you can have across all organizations with your current license."
                >
                    <span className="flex items-center">
                        Max # of team members
                        <IconInfo className="info-indicator text-xl" />
                    </span>
                </Tooltip>
            ),
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

    return (
        <div>
            <ConfirmCancelModal
                licenses={licenses}
                isOpen={!!showConfirmCancel}
                onCancel={() => setShowConfirmCancel(null)}
                onOk={() => (showConfirmCancel ? deleteLicense(showConfirmCancel) : null)}
            />
            <PageHeader title="Licenses" />

            <div className="flex flex-row flex-wrap gap-4 my-4 mb-8 items-start">
                <div className="flex-1">
                    <p>
                        Here you can add and manage your PostHog enterprise licenses. When you activate a license key,
                        enterprise functionality will be enabled immediately. Contact{' '}
                        <a href="mailto:sales@posthog.com">sales@posthog.com</a> for more information or if you have any
                        issues with a license.
                    </p>

                    <p>You will be billed after the first month based on usage.</p>
                    <p>
                        This license is for <strong>Self Hosted instances only</strong>, premium PostHog Cloud features
                        are billed separately.
                    </p>
                </div>

                <div>
                    <div className="border rounded p-8 px-10 shadow" style={{ minWidth: 500 }}>
                        {showExistingForm ? (
                            <>
                                <h2 className="text-center">Activate a PostHog license key</h2>
                                <Form
                                    logic={licenseLogic}
                                    formKey="activateLicense"
                                    enableFormOnSubmit
                                    className="space-y-4"
                                >
                                    <Field name="key" label={'License key'}>
                                        <LemonInput fullWidth />
                                    </Field>

                                    <LemonButton
                                        type="primary"
                                        htmlType="submit"
                                        loading={isActivateLicenseSubmitting}
                                        fullWidth
                                        center
                                        size="large"
                                    >
                                        Activate license key
                                    </LemonButton>
                                </Form>
                            </>
                        ) : (
                            <>
                                <h2 className="text-center">Get a PostHog license key</h2>
                                <Form
                                    logic={licenseLogic}
                                    formKey="createLicense"
                                    enableFormOnSubmit
                                    className="space-y-4"
                                >
                                    <Field name="client_name" label="Company Name">
                                        <LemonInput fullWidth />
                                    </Field>

                                    <Field
                                        name="billing_email"
                                        label="Billing Email"
                                        help="Your license key will also be sent to this email address"
                                    >
                                        <LemonInput fullWidth />
                                    </Field>

                                    <Field name="terms">
                                        <LemonCheckbox
                                            bordered
                                            fullWidth
                                            label={
                                                <>
                                                    I accept the{' '}
                                                    <Link target="_blank" to="https://posthog.com/terms">
                                                        terms and conditions
                                                    </Link>
                                                </>
                                            }
                                        />
                                    </Field>

                                    <LemonButton
                                        type="primary"
                                        htmlType="submit"
                                        loading={isActivateLicenseSubmitting}
                                        fullWidth
                                        center
                                        size="large"
                                    >
                                        Continue to verify card
                                    </LemonButton>
                                </Form>
                            </>
                        )}

                        <LemonDivider dashed className="my-4" />

                        <LemonButton fullWidth center onClick={() => setShowExistingForm(!showExistingForm)}>
                            {!showExistingForm ? 'I already have a license key' : "I don't have a license key"}
                        </LemonButton>
                    </div>
                </div>
            </div>

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
