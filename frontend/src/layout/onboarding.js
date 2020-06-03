import React, { useState, useEffect, useRef } from 'react'
import { Popover, Button, Checkbox, Badge } from 'antd'
import { useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { Loading } from 'lib/utils'
import { StarOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { NewActionModal } from 'scenes/actions/NewActionModal'

export default function OnboardingWidget() {
    const contentRef = useRef()
    const { actions, actionsLoading } = useValues(actionsModel)
    const [modalVisible, setModalVisible] = useState(false)
    const [visible, setVisible] = useState(true)

    let onClickOutside = event => {
        if (contentRef.current && !contentRef.current.contains(event.target)) {
            setVisible(false)
        }
    }

    useEffect(() => {
        document.addEventListener('mousedown', onClickOutside)
        return () => {
            document.removeEventListener('mousedown', onClickOutside)
        }
    }, [])

    function content({ actions }) {
        return (
            <div ref={contentRef} style={{ display: 'flex', width: '25vw', flexDirection: 'column' }}>
                <h2>Get Started</h2>
                <p>
                    Complete these steps to learn how to use Posthog! Click on an item below to learn how to complete it
                </p>
                <hr style={{ height: 5, visibility: 'hidden' }} />
                <Checkbox checked={actions.length > 0}>
                    <Link
                        onClick={() => {
                            setVisible(false)
                            setModalVisible(true)
                        }}
                    >
                        Create an Action
                    </Link>
                </Checkbox>
                <hr style={{ height: 5, visibility: 'hidden' }} />
                <Checkbox checked={false} onChange={e => console.log('changed')}>
                    <Link to={'/trends'} onClick={() => setVisible(false)}>
                        Create a trend graph
                    </Link>
                </Checkbox>
                <hr style={{ height: 5, visibility: 'hidden' }} />
                <Checkbox checked={false} onChange={e => console.log('changed')}>
                    <Link to={'/funnel/new'} onClick={() => setVisible(false)}>
                        Create a funnel
                    </Link>
                </Checkbox>
                <hr style={{ height: 5, visibility: 'hidden' }} />
                <p style={{ color: 'gray' }}>Don't show this again</p>
            </div>
        )
    }

    return (
        <div>
            <Popover
                visible={visible}
                content={actionsLoading ? <Loading></Loading> : content({ actions })}
                trigger="click"
            >
                <Badge count={3}>
                    <Button onClick={() => setVisible(!visible)}>
                        <StarOutlined></StarOutlined>
                    </Button>
                </Badge>
            </Popover>
            <NewActionModal
                visible={modalVisible}
                onVisibleChanged={visible => setModalVisible(visible)}
            ></NewActionModal>
        </div>
    )
}
