import React, { useState, useEffect, useRef } from 'react'
import { Popover, Button, Checkbox, Badge, Modal } from 'antd'
import { useValues, useActions } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { Loading } from 'lib/utils'
import { StarOutlined, StarFilled } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import FunnelImage from '../_assets/funnel_with_text.png'
import ActionImage from '../_assets/actions.png'
import TrendImage from '../_assets/trend.png'
import { onboardingLogic, TourType } from './onboardingLogic'
import { userLogic } from 'scenes/userLogic'
import _ from 'lodash'
import api from 'lib/api'

export function OnboardingWidget() {
    const contentRef = useRef()
    const { actions, actionsLoading } = useValues(actionsModel)
    const [instructionalModal, setInstructionalModal] = useState(false)
    const { user } = useValues(userLogic)
    const { loadUser } = useActions(userLogic)
    const { tourType, checked } = useValues(onboardingLogic({ user }))
    const { setTourActive, setTourType, updateOnboardingInitial } = useActions(onboardingLogic)
    const [visible, setVisible] = useState(user.onboarding.initial ? true : false)

    const unfinishedCount = _.filter(checked, isChecked => !isChecked).length

    function closePopup() {
        if (user.onboarding.initial) updateOnboardingInitial(false)
        setVisible(false)
    }

    let onClickOutside = event => {
        if (contentRef.current && !contentRef.current.contains(event.target)) {
            closePopup()
        }
    }

    useEffect(() => {
        document.addEventListener('mousedown', onClickOutside)
        return () => {
            document.removeEventListener('mousedown', onClickOutside)
        }
    }, [])

    async function dontShowAgain() {
        try {
            await api.update('api/user', { onboarding: { ...user.onboarding, active: false } })
            loadUser()
        } catch (err) {
            throw err
        }
    }

    function content() {
        return (
            <div ref={contentRef} style={{ display: 'flex', width: '25vw', flexDirection: 'column' }}>
                <h2>Get Started</h2>
                <p>
                    Complete these steps to learn how to use Posthog! Click on an item below to learn how to complete it
                </p>
                {Object.entries(TourType).map(([_, value], index) => {
                    return (
                        <div key={index}>
                            <hr style={{ height: 5, visibility: 'hidden' }} />
                            <Checkbox checked={user.onboarding.steps[index] || checked[index]}>
                                <Link
                                    onClick={() => {
                                        closePopup()
                                        setInstructionalModal(true)
                                        setTourType(value)
                                    }}
                                >
                                    Create {value}
                                </Link>
                            </Checkbox>
                        </div>
                    )
                })}
                <hr style={{ height: 5, visibility: 'hidden' }} />
                {unfinishedCount > 0 ? (
                    <p onClick={dontShowAgain} style={{ color: 'gray', cursor: 'pointer' }}>
                        Don't show this again
                    </p>
                ) : (
                    <Button onClick={dontShowAgain} type={'primary'}>
                        Done
                    </Button>
                )}
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
                <Badge count={unfinishedCount}>
                    <Button onClick={() => (visible ? closePopup() : setVisible(true))}>
                        {unfinishedCount === 0 ? <StarFilled></StarFilled> : <StarOutlined></StarOutlined>}
                    </Button>
                </Badge>
            </Popover>
            <Modal
                visible={instructionalModal}
                style={{ minWidth: '50%' }}
                bodyStyle={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}
                footer={null}
                onCancel={() => setInstructionalModal(false)}
            >
                <img style={{ maxWidth: '100%' }} src={ModalContent[tourType].src}></img>
                <h1 style={{ textAlign: 'center' }}>{ModalContent[tourType].title}</h1>
                <p style={{ textAlign: 'center' }}>{ModalContent[tourType].description}</p>
                <Button type="primary" style={{ textAlign: 'center' }}>
                    <Link
                        to={ModalContent[tourType].link}
                        onClick={() => {
                            setInstructionalModal(false)
                            closePopup()
                            setTimeout(() => setTourActive(), 500)
                        }}
                    >
                        {ModalContent[tourType].buttonText}
                    </Link>
                </Button>
            </Modal>
        </div>
    )
}

const ModalContent = {
    [TourType.ACTION]: {
        src: ActionImage,
        title: 'Actions',
        description:
            'Events can get overwhelming. Use actions to filter and group events you want to analyze as a distinct entity.',
        link: '/action',
        buttonText: 'Create Action',
    },
    [TourType.TRENDS]: {
        src: TrendImage,
        title: 'Trends',
        description: 'Trends show you aggregate data on actions and events',
        link: '/trends',
        buttonText: 'Create Trend Graph',
    },
    [TourType.FUNNEL]: {
        src: FunnelImage,
        title: 'Funnels',
        description: 'Funnels are used to understand how your users are converting from one step to the next.',
        link: '/funnel/new',
        buttonText: 'Create Funnel',
    },
}
