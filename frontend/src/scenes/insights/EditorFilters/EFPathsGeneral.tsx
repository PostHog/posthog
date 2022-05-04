import React from 'react'
import { useValues } from 'kea'
import { Col, Row } from 'antd'
import { AvailableFeature, EditorFilterProps } from '~/types'

import { userLogic } from 'scenes/userLogic'
import { PayCard } from 'lib/components/PayCard/PayCard'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
// import { PathAdvanded } from './PathAdvanced'

export function EFPathsGeneral({ insightProps }: EditorFilterProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const hasAdvancedPaths = user?.organization?.available_features?.includes(AvailableFeature.PATHS_ADVANCED) || true

    return (
        <>
            <Row>
                <Col span={12}>
                    <Col className="event-types" style={{ paddingBottom: 16 }}>
                        {/* {hasAdvancedPaths && (
                            <>
                                <hr />
                                <h4 className="secondary">Advanced options</h4>
                                <PathAdvanded />
                            </>
                        )} */}
                        {!hasAdvancedPaths && !preflight?.instance_preferences?.disable_paid_fs && (
                            <Row align="middle">
                                <Col span={24}>
                                    <PayCard
                                        identifier={AvailableFeature.PATHS_ADVANCED}
                                        title="Get a deeper understanding of your users"
                                        caption="Advanced features such as interconnection with funnels, grouping &amp; wildcarding and exclusions can help you gain deeper insights."
                                        docsLink="https://posthog.com/docs/user-guides/paths"
                                    />
                                </Col>
                            </Row>
                        )}
                    </Col>
                </Col>
            </Row>
        </>
    )
}
