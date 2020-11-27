import React from 'react'
import { hot } from 'react-hot-loader/root'
import { Alert, Form, Button, Table, Input } from 'antd'
import { licenseLogic } from './logic'
import { useValues, useActions } from 'kea'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { CodeSnippet } from 'scenes/ingestion/frameworks/CodeSnippet'
import { PageHeader } from 'lib/components/PageHeader'

const columns = [
    {
        title: 'Active',
        render: function renderActive(license: any) {
            return new Date(license.valid_until) > new Date() ? 'active' : 'expired'
        },
    },
    {
        title: 'Valid until',
        render: function renderActive(license: any) {
            return humanFriendlyDetailedTime(license.valid_until)
        },
    },
    {
        title: 'Plan',
        dataIndex: 'plan',
    },
    {
        title: 'Key',
        render: function renderActive(license: any) {
            return <CodeSnippet>{license.key}</CodeSnippet>
        },
    },
    {
        title: 'License added on',
        render: function renderActive(license: any) {
            return humanFriendlyDetailedTime(license.created_at)
        },
    },
]

export const Licenses = hot(_Licenses)
function _Licenses(): JSX.Element {
    const [form] = Form.useForm()
    const { licenses, licensesLoading, error } = useValues(licenseLogic)
    const { createLicense } = useActions(licenseLogic)

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
            <Table
                data-attr="license-table"
                size="small"
                rowKey="id"
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                rowClassName="cursor-pointer"
                dataSource={licenses}
                columns={columns}
                loading={licensesLoading}
            />
        </div>
    )
}
