import React from 'react'
import { hot } from 'react-hot-loader/root'
import { Alert, Form, Button, Table, Input } from 'antd'
import { licenseLogic } from './licenseLogic'
import { useValues, useActions } from 'kea'
import { humanFriendlyDetailedTime } from 'lib/utils'

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
            return <pre className="code">{license.key}</pre>
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
            <h1 className="page-header">Licenses</h1>
            <p style={{ maxWidth: 600 }}>
                <i>
                    Here you can add and manage your PostHog enterprise licenses. By adding a license key, you'll be
                    able to unluck enterprise functionality in PostHog right away!
                    <br />
                    <br />
                    Contact <a href="mailto:sales@posthog.com">sales@posthog.com</a> to buy a license.
                </i>
            </p>
            <br />
            {error && (
                <Alert
                    message={error.detail || <span>Something went wrong. Please try again or contact us.</span>}
                    type="error"
                />
            )}
            <br />
            <Form
                form={form}
                name="horizontal_login"
                layout="inline"
                onFinish={(values) => createLicense({ key: values.key })}
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
                                form.getFieldsError().filter(({ errors }) => errors.length).length
                            }
                        >
                            Activate License Key
                        </Button>
                    )}
                </Form.Item>
            </Form>
            <br />
            <Table
                data-attr="license-table"
                size="small"
                rowKey={(item): string => item.id}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                rowClassName="cursor-pointer"
                dataSource={licenses}
                columns={columns}
                loading={licensesLoading}
            />
        </div>
    )
}
