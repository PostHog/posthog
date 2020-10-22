import React, { useState } from 'react'
import { hot } from 'react-hot-loader/root'
import { useValues, useActions } from 'kea'
import { featureFlagLogic } from './featureFlagLogic'
import { Table, Switch, Drawer, Button } from 'antd'
import moment from 'moment'
import { EditFeatureFlag } from './EditFeatureFlag'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { LinkButton } from 'lib/components/LinkButton'

export const FeatureFlags = hot(_FeatureFlags)
function _FeatureFlags() {
    const [openFeatureFlag, setOpenFeatureFlag] = useState(false)
    const logic = featureFlagLogic({ closeDrawer: () => setOpenFeatureFlag(false) })
    const { featureFlags, featureFlagsLoading } = useValues(logic)
    const { updateFeatureFlag } = useActions(logic)

    let columns = [
        {
            title: 'Name',
            dataIndex: 'name',
        },
        {
            title: 'Key',
            dataIndex: 'key',
        },

        {
            title: 'Created at',
            render: function RenderCreatedAt(_, featureFlag) {
                return moment(featureFlag.created_at).format('LLL')
            },
        },
        {
            title: 'Created by',
            render: function RenderCreatedBy(_, featureFlag) {
                return featureFlag.created_by.first_name || featureFlag.created_by.email
            },
        },
        {
            title: 'Active',
            render: function RenderActive(featureFlag) {
                return (
                    <Switch
                        onClick={(_, e) => e.stopPropagation()}
                        checked={featureFlag.active}
                        onChange={(active) => updateFeatureFlag({ ...featureFlag, active })}
                    />
                )
            },
        },
        {
            title: 'Usage',
            render: function RenderActive(featureFlag) {
                return (
                    <LinkButton
                        to={
                            '/insights?events=[{"id":"$feature_flag_called","name":"$feature_flag_called","type":"events"}]&properties=[{"key":"$feature_flag","value":"' +
                            featureFlag.key +
                            '"}]#backTo=Feature Flags&backToURL=' +
                            window.location.pathname
                        }
                        type="primary"
                        data-attr="usage"
                    >
                        Usage
                    </LinkButton>
                )
            },
        },
    ]

    return (
        <div className="feature-flags">
            <h1 className="page-header">Feature Flags</h1>
            <p style={{ maxWidth: 600 }}>
                <i>Feature flags are a way of turning functionality in your app on or off, based on user properties.</i>
            </p>
            <Button type="primary" onClick={() => setOpenFeatureFlag('new')} data-attr="new-feature-flag">
                + New Feature Flag
            </Button>
            <br />
            <br />
            <Table
                dataSource={featureFlags}
                columns={columns}
                loading={!featureFlags && featureFlagsLoading}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                onRow={(featureFlag) => ({
                    onClick: () => setOpenFeatureFlag(featureFlag),
                })}
                size="small"
                rowClassName={'cursor-pointer ' + rrwebBlockClass}
                data-attr="feature-flag-table"
            />
            <Drawer
                title={openFeatureFlag === 'new' ? 'New feature flag' : openFeatureFlag.name}
                width={400}
                onClose={() => setOpenFeatureFlag(false)}
                destroyOnClose={true}
                visible={openFeatureFlag}
            >
                {openFeatureFlag === 'new' ? (
                    <EditFeatureFlag
                        isNew={true}
                        featureFlag={{ rollout_percentage: null, active: true }}
                        logic={logic}
                    />
                ) : (
                    <EditFeatureFlag featureFlag={openFeatureFlag} logic={logic} />
                )}
            </Drawer>
        </div>
    )
}
